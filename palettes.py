from PIL import Image

def get_colors(png_path):
  res = []
  with Image.open(png_path) as im:
    width, height = im.size
    img_data = im.load()
    for x in range(width):
      r = 0
      g = 0
      b = 0
      for y in range(height):
        (p_r, p_g, p_b, _) = img_data[x, y]
        r += p_r
        g += p_g
        b += p_b
      r /= height * 256
      g /= height * 256
      b /= height * 256
      res.append((r, g, b))
  return res

MAGMA_PALETTE = get_colors('palettes/magma.png')
SPECTRAL_PALETTE = get_colors('palettes/spectral.png')
VIRIDIS_PALETTE = get_colors('palettes/viridis.png')
