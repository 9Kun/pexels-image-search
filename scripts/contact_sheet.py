"""Numbered review sheets adapted from PPT Master ImageRotator (MIT)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size, text=""):
    faces = ["C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
    if any("\u3400" <= char <= "\u9fff" for char in text):
        faces.insert(0, "C:/Windows/Fonts/msyh.ttc")
    for face in faces:
        try:
            return ImageFont.truetype(face, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def create_contact_sheets(photos, directory, page):
    directory = Path(directory)
    outputs = []
    cell_width, cell_height = 520, 350
    for offset in range(0, len(photos), 8):
        group = photos[offset:offset + 8]
        columns = min(2, len(group))
        rows = (len(group) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_width, 70 + rows * cell_height), "#f4f6f8")
        draw = ImageDraw.Draw(sheet)
        draw.text((20, 16), f"Pexels candidates | API page {page}", fill="#172b4d", font=_font(24))
        draw.text((20, 46), "Photos provided by https://www.pexels.com", fill="#42526e", font=_font(14))
        for index, photo in enumerate(group):
            x, y = index % columns * cell_width, 70 + index // columns * cell_height
            draw.rectangle((x + 10, y + 10, x + 510, y + 340), fill="white", outline="#dfe3e8")
            preview = photo.get("preview_file")
            if preview:
                with Image.open(directory / preview) as original:
                    prepared = ImageOps.exif_transpose(original)
                    try:
                        thumb = prepared.convert("RGB")
                    finally:
                        if prepared is not original:
                            prepared.close()
                thumb.thumbnail((480, 260), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (x + 20 + (480 - thumb.width) // 2, y + 20 + (260 - thumb.height) // 2))
                thumb.close()
            else:
                draw.text((x + 35, y + 120), "Preview unavailable", fill="#a12727", font=_font(22))
            label = f"#{photo['candidate_number']:02d} | ID {photo['id']} | {photo['width']} x {photo['height']}"
            draw.text((x + 24, y + 288), label, fill="#172b4d", font=_font(17))
            author = str(photo.get("photographer", ""))[:40]
            draw.text((x + 24, y + 314), author, fill="#42526e", font=_font(14, author))
        filename = f"review_sheet_{offset // 8 + 1:02d}.jpg"
        sheet.save(directory / filename, format="JPEG", quality=92)
        sheet.close()
        outputs.append(filename)
    return outputs
