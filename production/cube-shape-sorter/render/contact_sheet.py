#!/usr/bin/env python3
"""Контактный лист тестовых кадров: test/contact_sheet.png (+ вариант с безопасными зонами 9:16).

Использование: python3 contact_sheet.py [папка_с_кадрами] [кадры через запятую]
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "test"
FRAMES = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "0,12,78,150,183,237,273,330,363,420,449").split(",")]
COLS, TW, TH, PAD, LAB = 4, 360, 640, 16, 44
NOTES = {0: "хук: падение", 12: "касание", 78: "БОНК о круг", 150: "застрял",
         183: "ЧПОК", 237: "уныние / блик", 273: "озарение", 330: "в квадрат!",
         363: "«бух» внутри", 420: "тень-твист", 449: "шов петли → 0"}


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def sheet(safe: bool) -> Image.Image:
    rows = (len(FRAMES) + COLS - 1) // COLS
    W = COLS * TW + (COLS + 1) * PAD
    H = rows * (TH + LAB) + (rows + 1) * PAD
    out = Image.new("RGB", (W, H), (34, 38, 44))
    d = ImageDraw.Draw(out)
    f1, f2 = font(24), font(18)
    for i, f in enumerate(FRAMES):
        im = Image.open(SRC / f"f_{f:04d}.png").convert("RGB")
        if safe:
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            od.rectangle([0, 0, 1080, 192], fill=(255, 0, 0, 60))        # верх 10%
            od.rectangle([0, 1536, 1080, 1920], fill=(255, 0, 0, 60))    # низ 20%
            od.rectangle([900, 192, 1080, 1536], fill=(255, 120, 0, 60))  # колонка кнопок
            od.rectangle([110, 260, 880, 1480], outline=(0, 90, 255, 200), width=4)  # рамка значимого
            im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        th = im.resize((TW, TH), Image.LANCZOS)
        c, r = i % COLS, i // COLS
        x = PAD + c * (TW + PAD)
        y = PAD + r * (TH + LAB + PAD)
        out.paste(th, (x, y + LAB))
        d.text((x + 4, y + 6), f"f{f:03d}  {f / 30:.2f} с", fill=(255, 255, 255), font=f1)
        d.text((x + 200, y + 12), NOTES.get(f, ""), fill=(190, 200, 210), font=f2)
    return out


if __name__ == "__main__":
    sheet(False).save(SRC / "contact_sheet.png")
    sheet(True).save(SRC / "contact_sheet_safezones.png")
    print(SRC / "contact_sheet.png")
