"""Owner-controlled immutable custody for human submissions; no actor execution."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from decimal import Decimal, InvalidOperation

import controlplane

MAX_ARTIFACT_BYTES = 256 * 1024
MAX_ARTIFACTS = 8
SCOPE_FIELDS = frozenset(('tenant_id', 'project_id', 'learner_id', 'course_revision', 'variant_revision'))
EXPOSURE_FIELDS = frozenset(('coverage','actor','assistance','answer_exposed','repeated_example','accommodation_allowed'))
MAX_EXPOSURE_EVENTS = 64


class SubmissionRefused(ValueError):
    pass


def canonical(value):
    def number(item):
        value = item if isinstance(item,Decimal) else Decimal(str(item))
        if not value.is_finite(): raise SubmissionRefused('non-finite JSON number')
        sign,digits,exponent=value.as_tuple()
        if not any(digits): return '0'
        digits=list(digits)
        while digits[-1]==0: digits.pop();exponent+=1
        coefficient=''.join(str(digit) for digit in digits)
        point=len(coefficient)+exponent
        prefix='-' if sign else ''
        if exponent>=0 and point<=4096: return prefix+coefficient+'0'*exponent
        if 0<point<len(coefficient): return prefix+coefficient[:point]+'.'+coefficient[point:]
        if point<=0 and -point+len(coefficient)<=4096: return prefix+'0.'+'0'*(-point)+coefficient
        return prefix+coefficient+'e'+str(exponent)
    def encode(item):
        if item is None: return 'null'
        if isinstance(item,bool): return 'true' if item else 'false'
        if isinstance(item,(int,float,Decimal)): return number(item)
        if isinstance(item,str): return json.dumps(item,ensure_ascii=True)
        if isinstance(item,(list,tuple)): return '['+','.join(encode(child) for child in item)+']'
        if isinstance(item,dict):
            if any(not isinstance(key,str) for key in item): raise SubmissionRefused('JSON object keys must be text')
            return '{'+','.join(encode(key)+':'+encode(item[key]) for key in sorted(item))+'}'
        raise SubmissionRefused('unsupported JSON value')
    try:
        return encode(value).encode('ascii')
    except (ValueError, TypeError, RecursionError, InvalidOperation) as error:
        if isinstance(error,SubmissionRefused): raise
        raise SubmissionRefused('invalid bounded submission metadata') from error


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 320 or '\0' in value:
        raise SubmissionRefused('invalid submission identity')
    return value


def scope_value(scope):
    if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
        raise SubmissionRefused('submission scope is incomplete')
    return {name:text(scope[name]) for name in sorted(SCOPE_FIELDS)}


def exposure_facts(value):
    if (not isinstance(value,dict) or set(value)!=EXPOSURE_FIELDS
            or value['coverage'] not in ('COMPLETE','UNKNOWN') or value['actor'] not in ('USER','AGENT','SHARED')
            or value['assistance'] not in ('NONE','ACCOMMODATION','HINT','ANSWER','EXECUTION')
            or any(not isinstance(value[key],bool) for key in ('answer_exposed','repeated_example','accommodation_allowed'))):
        raise SubmissionRefused('invalid host exposure facts')
    return json.loads(canonical(value))


def decode_artifact(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ARTIFACT_BYTES:
        raise SubmissionRefused('artifact bytes are outside bounds')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SubmissionRefused('duplicate artifact JSON key')
            result[key] = value
        return result
    def nonfinite(value):
        raise SubmissionRefused('non-finite artifact number')
    def exact_number(value):
        if len(value)>4096: raise SubmissionRefused('numeric literal exceeds bounds')
        try: result=Decimal(value)
        except InvalidOperation as error: raise SubmissionRefused('invalid exact numeric literal') from error
        if not result.is_finite(): raise SubmissionRefused('non-finite artifact number')
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite,parse_float=exact_number)
        pending = [(value, 0)]; nodes = 0
        while pending:
            item, depth = pending.pop(); nodes += 1
            if depth > 20 or nodes > 10000:
                raise SubmissionRefused('artifact structure exceeds bounds')
            if isinstance(item, dict): pending.extend((child, depth+1) for child in item.values())
            elif isinstance(item, list): pending.extend((child, depth+1) for child in item)
        canonical(value)
        return value
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        if isinstance(error, SubmissionRefused): raise
        raise SubmissionRefused('artifact is not bounded strict UTF-8 JSON') from error


class AttemptCustody:
    def __init__(self, home, *, project_id, key):
        if not isinstance(key, bytes) or len(key) < 32:
            raise SubmissionRefused('host custody key is required')
        self.project_id = text(project_id)
        self._root = Path(home).absolute() / 'org/tutor-human-submissions'
        self._key = key
        self._gate = threading.RLock()
        self._exposure_heads = {}
        self._safe_root()

    def _safe_root(self):
        for path in (self._root, *self._root.parents):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise SubmissionRefused('redirected submission custody path')

    def _path(self, kind, identity):
        self._safe_root()
        return self._root / (kind + '-' + digest(text(identity).encode('utf-8')) + '.json')

    def _scope(self, scope):
        result = scope_value(scope)
        if result['project_id'] != self.project_id:
            raise SubmissionRefused('foreign submission project')
        return result

    def _seal(self, body):
        return hmac.new(self._key, canonical(body), hashlib.sha256).hexdigest()

    def _read(self, kind, identity):
        path = self._path(kind, identity)
        if path.is_symlink(): raise SubmissionRefused('redirected custody record')
        try:
            with path.open('rb') as source: raw = source.read(MAX_ARTIFACT_BYTES+1)
            if len(raw) > MAX_ARTIFACT_BYTES: raise SubmissionRefused('custody record exceeds bounds')
            record = decode_artifact(raw)
            if set(record) != {'body', 'seal'} or not isinstance(record['seal'], str):
                raise SubmissionRefused('invalid custody envelope')
            if not hmac.compare_digest(record['seal'], self._seal(record['body'])):
                raise SubmissionRefused('changed custody metadata')
            return record['body']
        except (OSError, TypeError, KeyError) as error:
            raise SubmissionRefused('missing or invalid custody record') from error

    def _write(self, kind, identity, body):
        controlplane.owner_only('ingest immutable human submission')
        path = self._path(kind, identity)
        self._root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if self._read(kind, identity) != body: raise SubmissionRefused('immutable custody identity conflict')
            return body
        raw = canonical({'body':body, 'seal':self._seal(body)})
        if len(raw)>MAX_ARTIFACT_BYTES: raise SubmissionRefused('custody metadata exceeds bounds')
        with path.open('xb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
        return body

    def begin(self, attempt_id, scope, rubric_binding, *, initial_exposure=None):
        with self._gate:
            return self._write('attempt', attempt_id, {'schema':'tutor.human-attempt-custody/1',
                'attempt_id':text(attempt_id),'scope':self._scope(scope), 'rubric_binding':json.loads(canonical(rubric_binding)),
                'initial_exposure':exposure_facts(initial_exposure) if initial_exposure is not None else None})

    def read_exposure(self, attempt_id, scope):
        with self._gate:
            attempt=self._attempt(attempt_id,scope)
            path=self._path('exposure',attempt_id).with_suffix('.jsonl')
            if path.is_symlink(): raise SubmissionRefused('redirected exposure history')
            if not path.exists():
                if self._exposure_heads.get(attempt_id): raise SubmissionRefused('exposure history disappeared')
                return []
            with path.open('rb') as source: raw=source.read(MAX_ARTIFACT_BYTES+1)
            if len(raw)>MAX_ARTIFACT_BYTES or raw and not raw.endswith(b'\n'):
                raise SubmissionRefused('exposure history is oversized or partial')
            records=[]; previous=''
            for line in raw.splitlines():
                entry=decode_artifact(line)
                if not isinstance(entry,dict) or set(entry)!={'body','seal'}:
                    raise SubmissionRefused('invalid exposure envelope')
                body=entry['body']; seal=entry['seal']
                if (not isinstance(body,dict) or set(body)!={'schema','attempt_id','scope','sequence','previous','facts','recorded_at_utc'}
                        or body['schema']!='tutor.human-exposure/1' or body['attempt_id']!=attempt_id
                        or body['scope']!=self._scope(scope) or body['sequence']!=len(records)+1
                        or body['previous']!=previous or not isinstance(seal,str)
                        or not hmac.compare_digest(seal,self._seal(body))):
                    raise SubmissionRefused('changed exposure history')
                exposure_facts(body['facts']); records.append(entry); previous=seal
                if len(records)>MAX_EXPOSURE_EVENTS: raise SubmissionRefused('exposure event count exceeded')
            observed=(len(records),previous)
            expected=self._exposure_heads.get(attempt_id)
            if expected is not None and observed!=expected:
                raise SubmissionRefused('exposure history rolled back or changed outside host recording')
            if attempt.get('initial_exposure') is not None and (not records or records[0]['body']['facts']!=attempt['initial_exposure']):
                raise SubmissionRefused('initial exposure facts disappeared')
            self._exposure_heads[attempt_id]=observed
            return records

    def record_exposure(self, attempt_id, scope, facts):
        controlplane.owner_only('record human assessment exposure')
        facts=exposure_facts(facts)
        with self._gate:
            records=self.read_exposure(attempt_id,scope)
            if any(row['body']['facts']==facts for row in records): return records
            if len(records)>=MAX_EXPOSURE_EVENTS: raise SubmissionRefused('exposure event count exceeded')
            initial=self._attempt(attempt_id,scope).get('initial_exposure')
            if not records and initial is not None and facts!=initial:
                raise SubmissionRefused('initial exposure facts must be recorded first')
            body={'schema':'tutor.human-exposure/1','attempt_id':attempt_id,'scope':self._scope(scope),
                'sequence':len(records)+1,'previous':records[-1]['seal'] if records else '', 'facts':facts,
                'recorded_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
            entry={'body':body,'seal':self._seal(body)}
            raw=canonical(entry)+b'\n'
            path=self._path('exposure',attempt_id).with_suffix('.jsonl')
            if path.is_symlink(): raise SubmissionRefused('redirected exposure history')
            with path.open('ab') as output:
                output.write(raw); output.flush(); os.fsync(output.fileno())
            self._exposure_heads[attempt_id]=(len(records)+1,entry['seal'])
            return [*records,entry]

    def _attempt(self, attempt_id, scope):
        attempt = self._read('attempt', attempt_id)
        if attempt['scope'] != self._scope(scope): raise SubmissionRefused('foreign learner/tenant/course/variant')
        return attempt

    def ingest(self, attempt_id, scope, payload, mime='application/json'):
        controlplane.owner_only('snapshot human artifact')
        if mime != 'application/json': raise SubmissionRefused('unsupported artifact format')
        decode_artifact(payload)
        with self._gate:
            self._attempt(attempt_id, scope)
            if self._path('submitted-attempt',attempt_id).exists():
                raise SubmissionRefused('submitted attempt cannot receive later artifacts')
            slot_id = None
            for number in range(MAX_ARTIFACTS):
                candidate = digest(canonical([attempt_id,number]))
                if self._path('ingest-slot',candidate).exists():
                    prior = self._read('ingest-slot',candidate)
                    if prior['scope']!=self._scope(scope) or prior['attempt_id']!=attempt_id:
                        raise SubmissionRefused('artifact slot scope changed')
                    if prior['artifact_digest']==digest(payload):
                        self._read_blob(prior)
                        return {k:v for k,v in prior.items() if k not in ('blob_name','scope')}
                elif slot_id is None:
                    slot_id = candidate
            if slot_id is None: raise SubmissionRefused('attempt artifact upload limit reached')
            identity = digest(canonical([attempt_id, scope, digest(payload)]))
            blob = self._root / (identity + '.blob')
            if blob.is_symlink(): raise SubmissionRefused('redirected artifact')
            if blob.exists():
                if self._read_blob({'blob_name':blob.name,'artifact_digest':digest(payload),'size_bytes':len(payload)}) != payload:
                    raise SubmissionRefused('changed immutable artifact')
            else:
                try:
                    with blob.open('xb') as output:
                        output.write(payload); output.flush(); os.fsync(output.fileno())
                except OSError:
                    if blob.exists() and not blob.is_symlink(): blob.unlink()
                    raise
            receipt = {'schema':'tutor.human-artifact-receipt/1','attempt_id':attempt_id,
                'scope':self._scope(scope),'artifact_digest':digest(payload),'size_bytes':len(payload),
                'mime':mime,'blob_name':blob.name}
            self._write('artifact', identity, receipt)
            self._write('ingest-slot',slot_id,receipt)
            return {k:v for k,v in receipt.items() if k not in ('blob_name', 'scope')}

    def submit(self, submission_id, attempt_id, scope, artifact_digests):
        with self._gate:
            attempt = self._attempt(attempt_id, scope)
            if (not isinstance(artifact_digests, list) or not 1 <= len(artifact_digests) <= MAX_ARTIFACTS
                    or any(not isinstance(value,str) for value in artifact_digests)
                    or len(set(artifact_digests)) != len(artifact_digests)):
                raise SubmissionRefused('artifact manifest is empty, duplicated or oversized')
            for value in artifact_digests:
                if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                    raise SubmissionRefused('invalid artifact digest')
                identity = digest(canonical([attempt_id, scope, value]))
                receipt = self._read('artifact', identity)
                if receipt['scope'] != self._scope(scope) or receipt['attempt_id'] != attempt_id:
                    raise SubmissionRefused('artifact custody does not match attempt')
                self._read_blob(receipt)
            prior = self._path('submitted-attempt', attempt_id)
            body = {'schema':'tutor.human-submission-custody/1','submission_id':text(submission_id),
                'attempt_id':attempt_id,'scope':self._scope(scope),'rubric_binding':attempt['rubric_binding'],
                'artifact_digests':list(artifact_digests)}
            if prior.exists() and self._read('submitted-attempt',attempt_id) != body:
                raise SubmissionRefused('attempt already has an immutable submission')
            self._write('submission',submission_id,body)
            self._write('submitted-attempt',attempt_id,body)
            return body

    def _read_blob(self, receipt):
        name = receipt['blob_name']
        if not isinstance(name,str) or len(name)!=69 or not name.endswith('.blob') or any(c not in '0123456789abcdef' for c in name[:-5]):
            raise SubmissionRefused('invalid owned artifact path')
        blob = self._root / name
        if blob.is_symlink(): raise SubmissionRefused('redirected artifact')
        try:
            with blob.open('rb') as source: raw = source.read(MAX_ARTIFACT_BYTES+1)
        except OSError as error: raise SubmissionRefused('missing submitted artifact') from error
        if len(raw)!=receipt['size_bytes'] or digest(raw)!=receipt['artifact_digest']:
            raise SubmissionRefused('submitted bytes changed')
        decode_artifact(raw)
        return raw

    def read_submission(self, submission_id, scope):
        with self._gate:
            body = self._read('submission',submission_id)
            if body['scope'] != self._scope(scope): raise SubmissionRefused('foreign submission scope')
            self._attempt(body['attempt_id'],scope)
            blobs = []
            for value in body['artifact_digests']:
                identity = digest(canonical([body['attempt_id'],scope,value]))
                receipt = self._read('artifact',identity)
                if receipt['scope'] != self._scope(scope) or receipt['artifact_digest'] != value:
                    raise SubmissionRefused('changed artifact receipt scope')
                blobs.append(self._read_blob(receipt))
            return body, tuple(blobs)
