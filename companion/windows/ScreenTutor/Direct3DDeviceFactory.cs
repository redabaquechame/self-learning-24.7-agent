using System.Runtime.InteropServices;
using Windows.Graphics.DirectX.Direct3D11;
using WinRT;

namespace ScreenTutor;

internal static class Direct3DDeviceFactory
{
    private const uint D3D11CreateDeviceBgraSupport = 0x20;
    private const uint D3D11SdkVersion = 7;
    private const int D3DDriverTypeHardware = 1;
    private static readonly Guid IdxgiDevice = new("54EC77FA-1377-44E6-8C32-88FD5F44C84C");

    public static IDirect3DDevice Create()
    {
        Marshal.ThrowExceptionForHR(D3D11CreateDevice(
            0, D3DDriverTypeHardware, 0, D3D11CreateDeviceBgraSupport,
            0, 0, D3D11SdkVersion, out var d3dDevice, out _, out var context));
        nint dxgiDevice = 0;
        nint inspectable = 0;
        try
        {
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(d3dDevice, in IdxgiDevice, out dxgiDevice));
            Marshal.ThrowExceptionForHR(CreateDirect3D11DeviceFromDXGIDevice(dxgiDevice, out inspectable));
            return MarshalInterface<IDirect3DDevice>.FromAbi(inspectable);
        }
        finally
        {
            if (inspectable != 0) Marshal.Release(inspectable);
            if (dxgiDevice != 0) Marshal.Release(dxgiDevice);
            if (context != 0) Marshal.Release(context);
            if (d3dDevice != 0) Marshal.Release(d3dDevice);
        }
    }

    [DllImport("d3d11.dll", ExactSpelling = true)]
    private static extern int D3D11CreateDevice(
        nint adapter, int driverType, nint software, uint flags,
        nint featureLevels, uint featureLevelCount, uint sdkVersion,
        out nint device, out int selectedFeatureLevel, out nint immediateContext);

    [DllImport("d3d11.dll", ExactSpelling = true)]
    private static extern int CreateDirect3D11DeviceFromDXGIDevice(
        nint dxgiDevice, out nint graphicsDevice);
}
