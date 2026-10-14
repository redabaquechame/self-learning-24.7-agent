using System.IO;
using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

/// <summary>Source-derived bounded mappings. References contain metadata, never pixels or paths.</summary>
public sealed class FrameTransfer : IDisposable
{
    private sealed record Lease(string TransferId, MemoryMappedFile Map, int Length, long Expires)
    {
        internal readonly object WipeGate = new();
        internal bool Wiped;
    }
    private readonly string _session;
    private readonly byte[] _key;
    private readonly object _gate = new();
    private readonly List<Lease> _leases = new();
    private readonly List<Lease> _retiring = new();
    private readonly Timer _expiry;
    private bool _closed;
    private long _generation;

    public FrameTransfer(string bridgeSessionId, byte[] launchKey)
    {
        if (!Regex.IsMatch(bridgeSessionId, "^[A-Za-z0-9_-]{1,128}$") || launchKey.Length != 32)
            throw new InvalidDataException("Invalid frame-transfer binding.");
        _session = bridgeSessionId; _key = launchKey.ToArray();
        _expiry = new Timer(_ => Expire(), null, 250, 250);
    }

    public JsonElement Publish(CapturedFrame frame, JsonElement binding)
    {
        ArgumentNullException.ThrowIfNull(frame);
        long generation; byte[] key;
        lock (_gate)
        {
            if (_closed) throw new InvalidDataException("Frame transfer is closed.");
            generation = _generation; key = _key.ToArray();
        }
        byte[]? raw = null; byte[]? entropy = null; byte[]? sealedBytes = null; MemoryMappedFile? map = null;
        try
        {
            var now = Environment.TickCount64;
            var envelope = JsonSerializer.SerializeToElement(new {
                schema = "fleet.tutor.bridge.v1", protocol_version = "1.1", session_id = _session,
                bridge_epoch = 1, sequence = 1, message_id = "frame-auth", reply_to = (string?)null,
                deadline_monotonic_ms = now + 1000, cancellation_generation = 0,
                message_type = "CAPTURE_AUTHORIZATION", body = binding
            });
            BridgeCodec.Encode(key, envelope); // Closed shape; no authority is minted here.
            var receipt = frame.Receipt;
            var expires = binding.GetProperty("expires_at_monotonic_ms").GetInt64();
            if (expires <= now || binding.GetProperty("source_id").GetString() != receipt.SourceId
                || binding.GetProperty("source_revision").GetString() != receipt.SourceRevision
                || binding.GetProperty("capture_epoch").GetInt64() != receipt.CaptureEpoch)
                throw new InvalidDataException("Frame is outside current source authorization.");
            if (receipt.Width == 0 || receipt.Height == 0 || receipt.Width > 8192 || receipt.Height > 8192
                || (long)receipt.Width * receipt.Height * 4 != receipt.SizeBytes || receipt.SizeBytes > CaptureSession.MaxFrameBytes
                || receipt.PixelFormat is not ("BGRA8" or "BGRA8_PREMULTIPLIED"))
                throw new InvalidDataException("Invalid native frame bounds.");
            raw = frame.Pixels.ToArray();
            if (raw.Length != receipt.SizeBytes || Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() != receipt.ContentSha256)
                throw new InvalidDataException("Native frame digest mismatch.");
            var token = Guid.NewGuid().ToString("N");
            entropy = HMACSHA256.HashData(key, Encoding.UTF8.GetBytes("fleet.tutor.frame.v1\n" + _session + "\n" + token));
            sealedBytes = Seal(raw, entropy);
            if (sealedBytes.Length <= 0 || sealedBytes.Length > receipt.SizeBytes + 65536)
                throw new InvalidDataException("Protected frame outside bounds.");
            map = MemoryMappedFile.CreateNew("Local\\fleet-tutor-frame-" + _session + "-" + token,
                sealedBytes.Length + 4, MemoryMappedFileAccess.ReadWrite, MemoryMappedFileOptions.None, HandleInheritability.None);
            using (var view = map.CreateViewAccessor())
            { view.Write(0, sealedBytes.Length); view.WriteArray(4, sealedBytes, 0, sealedBytes.Length); }
            var reference = JsonSerializer.SerializeToElement(new {
                schema = "fleet.tutor.frame-reference.v1", transfer_id = token,
                frame_receipt = new { frame_id = receipt.FrameId, source_id = receipt.SourceId, source_revision = receipt.SourceRevision,
                    capture_epoch = receipt.CaptureEpoch, captured_at_monotonic_ms = receipt.CapturedAtMonotonicMilliseconds,
                    width = receipt.Width, height = receipt.Height, pixel_format = receipt.PixelFormat,
                    size_bytes = receipt.SizeBytes, content_sha256 = receipt.ContentSha256 }
            });
            lock (_gate)
            {
                if (_closed || generation != _generation || expires <= Environment.TickCount64
                    || _leases.Count + _retiring.Count >= 3
                    || _leases.Concat(_retiring).Sum(l => (long)l.Length) + sealedBytes.Length + 4 > 64 * 1024 * 1024)
                    throw new InvalidDataException("Frame transfer stopped, expired or at capacity.");
                _leases.Add(new Lease(token, map, sealedBytes.Length + 4, expires)); map = null;
            }
            return reference;
        }
        finally
        {
            if (map is not null) Wipe(new Lease("", map, sealedBytes?.Length + 4 ?? 0, 0));
            CryptographicOperations.ZeroMemory(key);
            if (raw is not null) CryptographicOperations.ZeroMemory(raw);
            if (entropy is not null) CryptographicOperations.ZeroMemory(entropy);
            if (sealedBytes is not null) CryptographicOperations.ZeroMemory(sealedBytes);
        }
    }

    public void Release(string transferId)
    {
        Lease? lease;
        lock (_gate)
        {
            lease = _leases.FirstOrDefault(item => item.TransferId == transferId);
            if (lease is null) return;
            _leases.Remove(lease); _retiring.Add(lease);
        }
        try { Wipe(lease); }
        finally { lock (_gate) _retiring.Remove(lease); }
    }

    private void Expire()
    {
        Lease[] expired;
        lock (_gate)
        {
            expired = _leases.Where(l => l.Expires <= Environment.TickCount64).ToArray();
            foreach (var lease in expired) { _leases.Remove(lease); _retiring.Add(lease); }
        }
        foreach (var lease in expired)
        {
            try { Wipe(lease); }
            finally { lock (_gate) _retiring.Remove(lease); }
        }
    }

    private static void Wipe(Lease lease)
    {
        lock (lease.WipeGate)
        {
            if (lease.Wiped) return;
            try
            {
                using var view = lease.Map.CreateViewAccessor(); var zero = new byte[65536];
                for (long offset = 0; offset < lease.Length; offset += zero.Length)
                    view.WriteArray(offset, zero, 0, (int)Math.Min(zero.Length, lease.Length - offset));
            }
            finally { lease.Map.Dispose(); lease.Wiped = true; }
        }
    }

    public void Dispose()
    {
        Lease[] leases;
        lock (_gate) { _closed = true; _generation++; leases = _leases.Concat(_retiring).Distinct().ToArray(); _leases.Clear(); _retiring.Clear(); CryptographicOperations.ZeroMemory(_key); }
        _expiry.Dispose(); foreach (var lease in leases) Wipe(lease);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Length; public IntPtr Data; }
    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, ref Blob entropy,
        IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);

    private static byte[] Seal(byte[] raw, byte[] entropy)
    {
        var input = new Blob { Length = raw.Length, Data = Marshal.AllocHGlobal(raw.Length) };
        var extra = new Blob { Length = entropy.Length, Data = Marshal.AllocHGlobal(entropy.Length) }; Blob output = default;
        try
        {
            Marshal.Copy(raw, 0, input.Data, raw.Length); Marshal.Copy(entropy, 0, extra.Data, entropy.Length);
            if (!CryptProtectData(ref input, null, ref extra, IntPtr.Zero, IntPtr.Zero, 1, out output)) throw new InvalidDataException("Frame protection unavailable.");
            var result = new byte[output.Length]; Marshal.Copy(output.Data, result, 0, result.Length); return result;
        }
        finally
        {
            Marshal.Copy(new byte[input.Length], 0, input.Data, input.Length); Marshal.FreeHGlobal(input.Data);
            Marshal.Copy(new byte[extra.Length], 0, extra.Data, extra.Length); Marshal.FreeHGlobal(extra.Data);
            if (output.Data != IntPtr.Zero) LocalFree(output.Data);
        }
    }
}
