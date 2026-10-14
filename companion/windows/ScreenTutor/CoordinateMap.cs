namespace ScreenTutor;

public sealed record GroundingGeometry(
    int SourceWidth, int SourceHeight,
    int CropX, int CropY, int CropWidth, int CropHeight,
    int ModelWidth, int ModelHeight,
    int DesktopOriginX, int DesktopOriginY,
    double NativeDpiScale);

public readonly record struct GroundingPoint(double X, double Y);

public sealed class CoordinateMap
{
    private readonly GroundingGeometry _geometry;

    public CoordinateMap(GroundingGeometry geometry)
    {
        ArgumentNullException.ThrowIfNull(geometry);
        if (geometry.SourceWidth <= 0 || geometry.SourceHeight <= 0
            || geometry.ModelWidth <= 0 || geometry.ModelHeight <= 0
            || geometry.CropX < 0 || geometry.CropY < 0
            || geometry.CropWidth <= 0 || geometry.CropHeight <= 0
            || geometry.CropX + geometry.CropWidth > geometry.SourceWidth
            || geometry.CropY + geometry.CropHeight > geometry.SourceHeight
            || !double.IsFinite(geometry.NativeDpiScale)
            || geometry.NativeDpiScale <= 0)
            throw new ArgumentOutOfRangeException(nameof(geometry), "Grounding geometry is invalid.");
        _geometry = geometry;
    }

    public GroundingPoint ModelToDesktopDip(GroundingPoint point)
    {
        RequireFinite(point);
        if (point.X < 0 || point.X > _geometry.ModelWidth
            || point.Y < 0 || point.Y > _geometry.ModelHeight)
            throw new ArgumentOutOfRangeException(nameof(point), "Model point is outside the resized crop.");
        var sourceX = _geometry.CropX
            + point.X * _geometry.CropWidth / _geometry.ModelWidth;
        var sourceY = _geometry.CropY
            + point.Y * _geometry.CropHeight / _geometry.ModelHeight;
        return new GroundingPoint(
            (_geometry.DesktopOriginX + sourceX) / _geometry.NativeDpiScale,
            (_geometry.DesktopOriginY + sourceY) / _geometry.NativeDpiScale);
    }

    public GroundingPoint DesktopDipToModel(GroundingPoint point)
    {
        RequireFinite(point);
        var sourceX = point.X * _geometry.NativeDpiScale - _geometry.DesktopOriginX;
        var sourceY = point.Y * _geometry.NativeDpiScale - _geometry.DesktopOriginY;
        var model = new GroundingPoint(
            (sourceX - _geometry.CropX) * _geometry.ModelWidth / _geometry.CropWidth,
            (sourceY - _geometry.CropY) * _geometry.ModelHeight / _geometry.CropHeight);
        if (model.X < 0 || model.X > _geometry.ModelWidth
            || model.Y < 0 || model.Y > _geometry.ModelHeight)
            throw new ArgumentOutOfRangeException(nameof(point), "Desktop point is outside the resized crop.");
        return model;
    }

    private static void RequireFinite(GroundingPoint point)
    {
        if (!double.IsFinite(point.X) || !double.IsFinite(point.Y))
            throw new ArgumentOutOfRangeException(nameof(point), "Point must be finite.");
    }
}
