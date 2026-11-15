"""Render the project's original neutral caravan icon at HA's two PNG densities."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    blue = "#237eb5"

    def box(coords):
        return tuple(value * 4 for value in coords)

    draw.rounded_rectangle(box((19, 49, 225, 195)), 128, fill=blue)
    draw.rounded_rectangle(box((29, 59, 215, 185)), 88, fill="#e9f4fc")
    draw.rounded_rectangle(box((44.5, 76.5, 123.5, 131.5)), 46, fill=blue)
    draw.rounded_rectangle(box((51.5, 83.5, 116.5, 124.5)), 18, fill="#a8d8f4")
    draw.line(box((84, 80, 84, 128)), fill=blue, width=28)
    draw.rounded_rectangle(box((144.5, 76.5, 197.5, 193.5)), 46, fill=blue)
    draw.rounded_rectangle(box((151.5, 83.5, 190.5, 186.5)), 18, fill="white")
    draw.ellipse(box((175, 139, 183, 147)), fill=blue)
    draw.line(box((220, 175, 240, 175, 240, 190)), fill=blue, width=40)
    draw.ellipse(box((56, 172, 96, 212)), fill=blue)
    draw.ellipse(box((67, 183, 85, 201)), fill="white")
    draw.line(box((39, 150, 122, 150)), fill="#f2a33b", width=36)
    output = ROOT / "custom_components/adria_mach/brand"
    for pixels, name in ((256, "icon.png"), (512, "icon@2x.png")):
        image.resize((pixels, pixels), Image.Resampling.LANCZOS).save(output / name)


if __name__ == "__main__":
    main()
