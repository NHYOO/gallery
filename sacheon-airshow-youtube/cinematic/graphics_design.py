#!/usr/bin/env python3
"""Author original informational cards, without inventing aircraft imagery.

These cards intentionally separate KF-21 facts and future concepts from the
user's airshow photography. Source photographs are never opened or changed.
"""
from __future__ import annotations

from pathlib import Path
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1920, 1080
WHITE = (238, 246, 251)
MUTED = (137, 161, 180)
CYAN = (90, 205, 226)
AMBER = (232, 178, 107)


def _font(root: Path, size: int, bold: bool = False):
    name = 'NotoSansKR-Bold.ttf' if bold else 'NotoSansKR-Regular.ttf'
    return ImageFont.truetype(str(root / 'assets' / 'fonts' / name), size)


def _base(seed: int = 1) -> Image.Image:
    """Subtle cinematic blue/amber atmosphere, authored entirely from code."""
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    blue = np.exp(-(((x - 1370) / 870)**2 + ((y - 420) / 600)**2))
    amber = np.exp(-(((x - 1670) / 640)**2 + ((y - 790) / 390)**2))
    rgb = np.empty((HEIGHT, WIDTH, 3), dtype=np.float32)
    for c, (a, b, d) in enumerate(((4, 7, 16), (11, 25, 9), (23, 35, 1))):
        rgb[..., c] = a + b * blue + d * amber
    rng = np.random.default_rng(seed)
    rgb += rng.normal(0, .7, (HEIGHT, WIDTH, 1)).astype(np.float32)
    im = Image.fromarray(np.clip(rgb, 0, 255).astype('uint8'), 'RGB')
    d = ImageDraw.Draw(im, 'RGBA')
    # Sparse drafting lines, not operational HUD data.
    for xx in range(140, WIDTH, 140):
        d.line((xx, 190, xx, 850), fill=(110, 162, 185, 13), width=1)
    for yy in range(240, 850, 140):
        d.line((100, yy, 1820, yy), fill=(110, 162, 185, 12), width=1)
    d.line((110, 228, 320, 228), fill=(*AMBER, 220), width=3)
    return im


def _label(im, root, msg, x=112, y=266, size=25, color=MUTED):
    ImageDraw.Draw(im).text((x, y), msg, font=_font(root, size), fill=color)


def _text(im, root, msg, x, y, size, color=WHITE, bold=False):
    ImageDraw.Draw(im).text((x, y), msg, font=_font(root, size, bold), fill=color)


def _glow_ring(im, center, radii, color=CYAN):
    layer = Image.new('RGBA', im.size)
    d = ImageDraw.Draw(layer)
    cx, cy = center
    for j, r in enumerate(radii):
        d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(*color, max(35, 160-j*30)), width=2)
    glow = layer.filter(ImageFilter.GaussianBlur(8))
    im.paste(Image.alpha_composite(glow, layer), (0, 0), Image.alpha_composite(glow, layer))


def kf21_card(root: Path) -> Image.Image:
    im = _base(3)
    _label(im, root, 'FROM IDEA TO FLIGHT', color=CYAN)
    _text(im, root, 'KF-21', 105, 320, 198, bold=True)
    _text(im, root, '보라매', 114, 565, 80, bold=True)
    _text(im, root, '대한민국이 주도한 전투기 개발', 118, 706, 35, MUTED)
    _glow_ring(im, (1500, 520), (95, 170, 250))
    d = ImageDraw.Draw(im, 'RGBA')
    d.line((1215, 520, 1785, 520), fill=(*CYAN, 100), width=1)
    d.line((1500, 235, 1500, 805), fill=(*CYAN, 100), width=1)
    d.arc((1250, 270, 1750, 770), 295, 358, fill=(*AMBER, 220), width=5)
    _text(im, root, 'BORAMAE', 1390, 800, 26, MUTED)
    return im


def features_card(root: Path) -> Image.Image:
    im = _base(4)
    _label(im, root, 'SEE FARTHER. FLY FASTER.', color=CYAN)
    _text(im, root, '기술이 넓히는 하늘', 110, 330, 79, bold=True)
    _text(im, root, '국산 AESA 레이더', 116, 505, 53, bold=True)
    _text(im, root, '전자적으로 빔을 조향하는 능동 위상배열 레이더', 120, 588, 28, MUTED)
    _text(im, root, '초음속 전투기', 116, 708, 49, bold=True)
    _text(im, root, '독자적인 항공 기술을 향한 도전', 120, 786, 28, MUTED)
    _glow_ring(im, (1510, 555), (70, 130, 190, 250))
    d = ImageDraw.Draw(im, 'RGBA')
    # The sector only explains electronic scanning; it is not real radar output.
    d.pieslice((1260, 305, 1760, 805), 284, 330, fill=(55, 150, 173, 28))
    for angle in (284, 330):
        a = math.radians(angle)
        d.line((1510,555,1510+250*math.cos(a),555+250*math.sin(a)), fill=(*CYAN,130), width=2)
    _text(im, root, '원리 설명 그래픽', 1387, 839, 23, MUTED)
    return im


def timeline_card(root: Path) -> Image.Image:
    im = _base(5)
    _label(im, root, 'A DREAM, BUILT OVER TIME', color=CYAN)
    _text(im, root, '설계도에서 하늘로', 110, 330, 83, bold=True)
    d = ImageDraw.Draw(im, 'RGBA')
    d.line((140, 620, 1760, 620), fill=(*CYAN, 95), width=2)
    nodes = ((220, '2015', '체계개발 착수'), (840, '2022', '첫 비행'), (1460, 'NEXT', '시험과 진화'))
    for x, year, caption in nodes:
        d.ellipse((x-9, 611, x+9, 629), fill=AMBER)
        d.ellipse((x-22,598,x+22,642), outline=(*AMBER,65), width=1)
        _text(im, root, year, x-70, 495, 55, bold=True)
        _text(im, root, caption, x-70, 680, 40, WHITE)
    _text(im, root, '설계 · 제작 · 지상시험 · 비행시험', 150, 804, 33, MUTED)
    return im


def future_card(root: Path) -> Image.Image:
    im = _base(6)
    _label(im, root, 'THE NEXT CHAPTER', color=CYAN)
    _text(im, root, '함께 나는 미래', 110, 330, 88, bold=True)
    _text(im, root, '유·무인 협업', 119, 514, 58, bold=True)
    _text(im, root, '사람과 지능형 시스템이 연결되는 하늘', 122, 612, 33, MUTED)
    _text(im, root, '미래 기술 구상', 122, 758, 34, AMBER)
    # Abstract network, deliberately not a depiction of actual aircraft.
    center = (1435, 545)
    nodes = [(1220,390), (1635,355), (1720,610), (1455,780), (1170,690)]
    d = ImageDraw.Draw(im, 'RGBA')
    for j, node in enumerate(nodes):
        d.line((*center, *node), fill=(*CYAN,100), width=2)
        nx,ny=node
        d.ellipse((nx-22,ny-22,nx+22,ny+22), outline=(*CYAN,180), width=2)
        d.ellipse((nx-5,ny-5,nx+5,ny+5), fill=(*CYAN,230))
    _glow_ring(im, center, (48,70), AMBER)
    d = ImageDraw.Draw(im, 'RGBA')
    d.ellipse((center[0]-9,center[1]-9,center[0]+9,center[1]+9),fill=AMBER)
    _text(im, root, '개념 시각화', 1530, 842, 23, MUTED)
    return im


def generate_graphics(root: Path | str | None = None) -> list[Path]:
    root = Path(root) if root else Path(__file__).resolve().parent
    destination = root / 'assets' / 'graphics'
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, maker in (('03_kf21.png',kf21_card),('04_features.png',features_card),('05_timeline.png',timeline_card),('06_future.png',future_card)):
        path = destination / name
        maker(root).save(path, compress_level=5)
        outputs.append(path)
    return outputs


if __name__ == '__main__':
    for path in generate_graphics():
        print(path)
