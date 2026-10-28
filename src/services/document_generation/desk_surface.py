"""Realistic desk/surface background and shadow renderer for photo document simulation."""

from PIL import Image, ImageDraw, ImageFilter


def create_desk_surface(width: int, height: int, wood_tone: bool = True) -> Image.Image:
    """Create a textured desk surface (warm wood or neutral office desk)."""
    base_color = "#C8A27A" if wood_tone else "#DDD7CD"
    line_color = "#BD966F" if wood_tone else "#D2CCC0"

    desk = Image.new("RGB", (width, height), color=base_color)
    draw = ImageDraw.Draw(desk)
    step = 7 if wood_tone else 6
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
    return desk


def render_on_desk(
    image: Image.Image,
    angle: float = 0.0,
    padding: int = 120,
    wood_tone: bool = True,
    is_card: bool = False,
) -> Image.Image:
    """Render an ID card or document sheet resting on a desk surface with realistic soft drop shadow.

    Args:
        image: The rendered card or paper sheet.
        angle: Tilt angle in degrees (0.0 for straight photo, e.g. 15.0 for diagonal photo).
        padding: Margin around the document showing the desk.
        wood_tone: Warm wood desk vs neutral office desktop.
        is_card: Whether the object is a rounded ID card or rectangular paper sheet.
    """
    if abs(angle) < 0.1:
        bg_w, bg_h = image.width + padding * 2, image.height + padding * 2
        desk = create_desk_surface(bg_w, bg_h, wood_tone=wood_tone)

        # Soft shadow
        sh_w, sh_h = image.width + 40, image.height + 40
        shadow = Image.new("RGBA", (sh_w, sh_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        if is_card:
            sdraw.rounded_rectangle([(15, 15), (sh_w - 15, sh_h - 15)], radius=24, fill=(35, 30, 25, 110))
        else:
            sdraw.rectangle([(15, 15), (sh_w - 15, sh_h - 15)], fill=(35, 30, 25, 95))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))

        pos_x = padding
        pos_y = padding
        desk.paste(shadow, (pos_x - 10, pos_y - 8), shadow)
        desk.paste(image, (pos_x, pos_y))
        return desk
    else:
        rot_img = image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        mask = Image.new("L", image.size, 255).rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

        bg_w, bg_h = rot_img.width + padding * 2, rot_img.height + padding * 2
        desk = create_desk_surface(bg_w, bg_h, wood_tone=wood_tone)

        # Rotated soft shadow
        shadow = Image.new("RGBA", mask.size, (35, 30, 25, 110 if is_card else 95))
        shadow.putalpha(mask)
        shadow = shadow.filter(ImageFilter.GaussianBlur(16))

        pos_x = padding
        pos_y = padding
        desk.paste(shadow, (pos_x + 10, pos_y + 14), shadow)
        desk.paste(rot_img, (pos_x, pos_y), mask)
        return desk
