#!/usr/bin/env python3
"""Feature-gated request entrypoint from a selected native source to Fleet."""

import copy

import tutor_contracts as contracts
from tutor_session import TutorSession


class TutorUnavailable(RuntimeError):
    pass


class TutorService:
    def __init__(self, enabled=False, dispatch=None):
        self.enabled = enabled is True
        self.dispatch = dispatch

    def _admit(self, request, owner_state, observations, session):
        if not self.enabled:
            raise TutorUnavailable("screen tutor is disabled")
        if not isinstance(session, TutorSession) or session.state != "READY":
            raise TutorUnavailable("selected source session is not ready")
        verdict = contracts.authorize_tutor_request(request, owner_state)
        if not verdict["allowed"]:
            return verdict
        if any(request[key] != getattr(session, key) for key in
               ("session_id", "user_id", "tenant_id", "project_id")):
            return {"allowed": False, "reason_code": "REFUSE_CONTEXT_ACCESS",
                    "record_id": request["request_id"],
                    "detail": "request does not belong to the current selected-source session"}
        if not request["observation_ids"] or not request["source_ids"]:
            return {"allowed": False, "reason_code": "STALE_SOURCE",
                    "record_id": request["request_id"],
                    "detail": "a selected source observation is required"}
        by_id = {item.get("observation_id"): item for item in observations
                 if isinstance(item, dict)}
        requested_observations = []
        for observation_id in request["observation_ids"]:
            observation = by_id.get(observation_id)
            if observation is None:
                return {"allowed": False, "reason_code": "STALE_SOURCE",
                        "record_id": request["request_id"], "detail": observation_id}
            if observation.get("session_id") != session.session_id:
                return {"allowed": False, "reason_code": "REFUSE_CONTEXT_ACCESS",
                        "record_id": request["request_id"],
                        "detail": "observation does not belong to this session"}
            observed = contracts.validate_observation(observation, owner_state)
            if not observed["allowed"]:
                return observed
            if observation["source_id"] not in request["source_ids"]:
                return {"allowed": False, "reason_code": "STALE_SOURCE",
                        "record_id": request["request_id"],
                        "detail": observation["source_id"]}
            requested_observations.append(observation)
        if set(request["source_ids"]) != {
                observation["source_id"] for observation in requested_observations}:
            return {"allowed": False, "reason_code": "STALE_SOURCE",
                    "record_id": request["request_id"],
                    "detail": "every requested source requires a bound observation"}
        gate = contracts.check_generation(request["cancellation_generation"],
                                          session.cancellation_generation,
                                          "provider_dispatch")
        if not gate["allowed"]:
            return gate
        primary = requested_observations[0]
        if (session.source is None or primary["source_id"] != session.source.source_id
                or primary["source_revision"] != session.source.source_revision
                or primary["capture_epoch"] != session.capture_epoch):
            return {"allowed": False, "reason_code": "STALE_SOURCE",
                    "record_id": request["request_id"],
                    "detail": "primary observation is not the current selected source"}
        return requested_observations

    def ask(self, request, owner_state, observations, session):
        requested_observations = self._admit(request, owner_state, observations, session)
        if isinstance(requested_observations, dict):
            return requested_observations
        if self.dispatch is None:
            raise TutorUnavailable("no qualified provider dispatch adapter")
        instruction = self.dispatch(request, requested_observations)
        render_policy = {**owner_state,
                         "cancellation_generation": request["cancellation_generation"],
                         "current_cancellation_generation": session.cancellation_generation,
                         "request_id": request["request_id"],
                         "mode": request["mode"]}
        primary = requested_observations[0]
        return contracts.validate_instruction(instruction, primary, render_policy)

    def ask_current(self, request, current_owner_state, observations, session):
        """Release actual instruction content under current host authority.

        Only the host supplies the live policy reader and dispatch adapter.
        A permitted answer is not an action grant or independent learning.
        """
        if not self.enabled:
            raise TutorUnavailable("screen tutor is disabled")
        if not callable(current_owner_state):
            raise TutorUnavailable("current host-state reader is required")
        def read_owner():
            value = current_owner_state()
            if not isinstance(value, dict):
                raise TutorUnavailable("current host state is unavailable")
            return copy.deepcopy(value)
        owner = read_owner()
        admitted = self._admit(request, owner, observations, session)
        if isinstance(admitted, dict):
            return admitted
        if self.dispatch is None:
            raise TutorUnavailable("no qualified provider dispatch adapter")
        instruction = self.dispatch(copy.deepcopy(request), copy.deepcopy(admitted))
        owner_now = read_owner()
        try:
            admitted_now = self._admit(request, owner_now, observations, session)
        except TutorUnavailable:
            return {"allowed": False, "reason_code": "SUPPRESS_STALE_RESPONSE",
                    "record_id": request["request_id"]}
        if isinstance(admitted_now, dict):
            return admitted_now
        render_policy = {**owner_now,
                         "cancellation_generation": request["cancellation_generation"],
                         "current_cancellation_generation": session.cancellation_generation,
                         "request_id": request["request_id"], "mode": request["mode"]}
        verdict = contracts.validate_instruction(instruction, admitted_now[0], render_policy)
        if not verdict["allowed"]:
            return {**verdict, "failure_stage": "INSTRUCTION_VALIDATION"}
        return {**verdict, "instruction": copy.deepcopy(instruction)}

    def investigate(self, request, current_owner_state, observations, session, investigator,
                    *, source_keys=(), acquirer=None, sample_key=None, samples=None):
        """Read-only investigation through the same admission gate as model work.

        The host supplies the investigator and a live owner-state reader. Neither
        dependency is selected by request text. This route authorizes no input or
        application input and makes no paid provider call. Optional document
        keys refer only to the supplied host-owned acquisition policy.
        """
        if not self.enabled:
            raise TutorUnavailable("screen tutor is disabled")
        if not callable(current_owner_state):
            raise TutorUnavailable("current host-state reader is required")
        from tutor_investigation import (Investigation, InvestigationRefused,
                                        SourceAcquisition, ReversibleSamples)
        if not isinstance(investigator, Investigation):
            raise TutorUnavailable("host-owned investigation adapter is required")
        owner = current_owner_state()
        admitted = self._admit(request, owner, observations, session)
        if isinstance(admitted, dict):
            return admitted
        sample = None
        try:
            if (not isinstance(source_keys, (tuple, list)) or len(source_keys) > 8
                    or any(not isinstance(key, str) for key in source_keys)):
                raise InvestigationRefused('ACQUISITION_DENIED', 'invalid document selection')
            references = None
            if source_keys:
                import os
                if (not isinstance(acquirer, SourceAcquisition)
                        or os.path.realpath(acquirer.home) != os.path.realpath(investigator.home)
                        or acquirer.context._scope() != investigator._scope()):
                    raise InvestigationRefused('ACQUISITION_DENIED', 'host document adapter scope disagrees')
                references = []
                for key in source_keys:
                    before = self._admit(request, current_owner_state(), observations, session)
                    if isinstance(before, dict):
                        return before
                    references.append(acquirer.acquire(key)['reference'])
                    after = self._admit(request, current_owner_state(), observations, session)
                    if isinstance(after, dict):
                        return after
            answer = investigator.explain(request["question"], references=references, observation=admitted[0],
                                          observation_state=owner)
            # Recheck grants, expiry, identity, selection and generation after retrieval.
            admitted_now = self._admit(request, current_owner_state(), observations, session)
            if isinstance(admitted_now, dict):
                return admitted_now
            investigator.verify(answer)
            if sample_key is not None:
                if not isinstance(samples, ReversibleSamples) or samples.investigator is not investigator:
                    raise InvestigationRefused('SAMPLE_DENIED', 'host sample adapter does not match investigation')
                # Explicit host sample policy/permission is separate from the
                # closed v1 observe/explain/annotate mode-capability vocabulary.
                sample = samples.create(answer, sample_key)
            release = self._admit(request, current_owner_state(), observations, session)
            if isinstance(release, dict):
                if sample is not None:
                    samples.stop(sample['handle'])
                return release
            if investigator._scope() != answer['scope']:
                raise InvestigationRefused('STALE_CONTEXT', 'app/version context changed before release')
            if sample is not None:
                samples.validate(sample['handle'])
        except InvestigationRefused as error:
            if sample is not None:
                samples.stop(sample['handle'])
            return {"allowed": False, "reason_code": error.code,
                    "record_id": request["request_id"],
                    "detail": "investigation evidence is no longer eligible"}
        except TutorUnavailable:
            if sample is not None:
                samples.stop(sample['handle'])
            return {"allowed": False, "reason_code": "STALE_SOURCE",
                    "record_id": request["request_id"],
                    "detail": "selected-source session became unavailable"}
        result = {"allowed": True, "reason_code": "OK", "record_id": request["request_id"],
                "investigation": answer, "grant_created": False,
                "task_success_claimed": False, "learning_success_claimed": False}
        if sample is not None:
            result['sample'] = sample
        return result
