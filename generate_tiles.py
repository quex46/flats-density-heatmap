import os
import math
import multiprocessing
import sys
import json
from multiprocessing import Pool
import pandas as pd
from PIL import Image
from palettes import SPECTRAL_PALETTE as PALETTE

INPUT_FILE = './objects_geocoded.csv' # Columns: year, living_flats, address, latitude, longitude
TILE_SIZE = 256

def create_buckets(first, last, count):
  step = int((last - first) / count)
  buckets = []
  for i in range(count - 1):
    buckets.append(int(first + i * step))
  buckets.append(int(last))
  return buckets[::-1]

# Picks N colors from a color palette
def create_color_map(color_palette, n_colors):
  colors = []
  for i in range(n_colors):
    r, g, b = color_palette[int((len(color_palette)-1) * (float(i)/n_colors))]
    colors.append((int(r * 256), int(g * 256), int(b * 256)))
  return colors

# Calculates distance between two (x, y) points
def distance(point1, point2):
  (x1, y1) = point1
  (x2, y2) = point2
  return math.sqrt((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1))

# Calculates color of a pixel for a provided value
def color(val, buckets, colors):
  if weight is None:
    return (255, 255, 255, 0)
  assert len(colors) - 1 == len(buckets)
  for bucket_val, color in zip(buckets, colors):
    if val > bucket_val:
      return color
  return colors[-1]

# Checks if point is inside circle
def inside_radius(point, circle):
  (x, y) = point
  (c_x, c_y, r) = circle
  return math.hypot(c_x - x, c_y - y) <= r

# Inverse Distance Weighting (IDW) Interpolation
# https://gisgeography.com/inverse-distance-weighting-idw-interpolation/
def idw_interpolate(target_point, points, power, min_count, radius):
  num = 0
  den = 0
  c = 0
  neighbors = 0
  for point in points:
    (x, y, weight) = point
    (t_x, t_y) = target_point
    if radius != None and inside_radius((x, y), (t_x, t_y, radius)):
      neighbors += 1
    if x == t_x and y == t_y:
      return weight
    dist = distance((x, y), (t_x, t_y))
    d = 1 / (dist ** power)
    num += weight * d
    den += d
    c += 1
  # We won't calculate value for a point if it's too far from dataset's ones
  # (helps to avoid lakes, woods, etc)
  if radius != None and neighbors <= min_count:
    return None
  if c < min_count:
    return None
  return num / den

# LatLng to World coordinate
def ll_to_world(lat, lng):
  siny = math.sin((lat * math.pi) / 180)
  siny = min(max(siny, -0.9999), 0.9999)
  x = TILE_SIZE * (0.5 + lng / 360)
  y = TILE_SIZE * (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi))
  return (x, y)

# World coordinate to Pixel coordinate
def world_to_pixel(point, zoom_level):
  (x, y) = point
  scale = 1 << zoom_level
  return (math.floor(x * scale), math.floor(y * scale))

# World coordinate to Tile coordinate
def world_to_tile(point, zoom_level):
  (x, y) = point
  scale = 1 << zoom_level
  return (math.floor(x * scale / TILE_SIZE), math.floor(y * scale / TILE_SIZE))

# Reduces size of a dataset by recursively splitting it to smaller areas
# and merging points inside those areas using weighted average.
def reduce_dataset(input_df, output_df, min_size, min_count):
  if len(input_df) == 0:
    return output_df
  left = input_df['world_x'].min()
  right = input_df['world_x'].max()
  top = input_df['world_y'].min()
  bottom = input_df['world_y'].max()
  width = right - left
  height = bottom - top
  if (width <= min_size or height <= min_size) or len(input_df) < min_count:
    x = 0.0
    y = 0.0
    w = 0.0
    for row in input_df.to_dict('records'):
      x += (row['world_x'] * row['weight'])
      y += (row['world_y'] * row['weight'])
      w += row['weight']
    return output_df.append({
      'world_x': x / w,
      'world_y': y / w,
      'weight': w,
    }, ignore_index=True)
  mid_x = left + width / 2
  mid_y = top + height / 2
  output_df = reduce_dataset(input_df[(input_df['world_x'] > left) & (input_df['world_x'] <= mid_x) & (input_df['world_y'] > top) & (input_df['world_y'] <= mid_y)], output_df, min_size, min_count)
  output_df = reduce_dataset(input_df[(input_df['world_x'] > mid_x) & (input_df['world_x'] <= right) & (input_df['world_y'] > top) & (input_df['world_y'] <= mid_y)], output_df, min_size, min_count)
  output_df = reduce_dataset(input_df[(input_df['world_x'] > left) & (input_df['world_x'] <= mid_x) & (input_df['world_y'] > mid_y) & (input_df['world_y'] <= bottom)], output_df, min_size, min_count)
  output_df = reduce_dataset(input_df[(input_df['world_x'] > mid_x) & (input_df['world_x'] <= right) & (input_df['world_y'] > mid_y) & (input_df['world_y'] <= bottom)], output_df, min_size, min_count)
  return output_df

def process_tile(tile):
  # During experiments these values give pretty fine looking results
  POWER = 1.7
  RADIUS = 0.025
  MIN_COUNT = 1

  (tile_x, tile_y, zoom_level, i) = tile
  tile_path = f'tiles/{zoom_level}/{tile_x}/{tile_y}.png'
  if os.path.exists(tile_path):
    return None
  img = Image.new('RGBA', (TILE_SIZE, TILE_SIZE))
  img_data = img.load()

  points = []
  df_dict = reduced_df.to_dict('records')
  for row in df_dict:
    points.append((row['world_x'], row['world_y'], row['weight']))

  for x in range(TILE_SIZE):
    for y in range(TILE_SIZE):
      world_x = ((tile_x * TILE_SIZE + x) / (1 << zoom_level))
      world_y = ((tile_y * TILE_SIZE + y) / (1 << zoom_level))
      val = idw_interpolate((world_x, world_y), points, POWER, MIN_COUNT, RADIUS)
      img_data[x, y] = color(val, buckets, colors)
  os.makedirs(os.path.dirname(tile_path), exist_ok=True)
  img.save(tile_path, 'PNG')
  if i % 20 == 0:
    print(f'[{zoom_level}] Processed {i} of {len(tiles)} tiles')

# Saint-Petersburg bounds
(bounds_left, bounds_top) = ll_to_world(60.149193, 29.962670)
(bounds_right, bounds_bottom) = ll_to_world(59.751451, 30.698031)

df = pd.read_csv(INPUT_FILE, index_col=False)
# Filter possible invalid results from the dataset
df = df[(df['year'] < 2025) & (df['year'] > 1900) & (df['living_flats'] < 2000) & (df['living_flats'] > 2)]

df['weight'] = df['living_flats'] # Just use flats count as weight.

# Calculate world coordinates
df['world_x'] = pd.Series([], dtype='float64')
df['world_y'] = pd.Series([], dtype='float64')
for index, row in df.iterrows():
  (x, y) = ll_to_world(row['latitude'], row['longitude'])
  df.at[index, 'world_x'] = x
  df.at[index, 'world_y'] = y

# Filter out points out of the bounds
df = df[(df['world_x'] >= bounds_left) & (df['world_x'] <= bounds_right) & (df['world_y'] >= bounds_top) & (df['world_y'] <= bounds_bottom)]
# Drop unnecessary fields
df.drop(['address', 'year', 'living_flats'], axis=1, inplace=True)

legends = [] # This data will be exposed to frontend later.

processes = int(multiprocessing.cpu_count() * 0.85) # Use 85% of allowed CPUs
print(f'Threads: {processes}')

# Generate tiles
for zoom_level in [10, 11, 12, 13, 14, 15]:
  print(f'Processing tiles at {zoom_level} zoom level...')
  tiles = []
  (min_tile_x, min_tile_y) = world_to_tile((bounds_left, bounds_top), zoom_level)
  (max_tile_x, max_tile_y) = world_to_tile((bounds_right, bounds_bottom), zoom_level)
  i = 0
  for x in range(min_tile_x, max_tile_x + 1):
    for y in range(min_tile_y, max_tile_y + 1):
      i += 1
      tiles.append((x, y, zoom_level, i))

  [min_size, min_count] = {
    '9': [0.016, 3],
    '10': [0.016, 3],
    '11': [0.015, 3],
    '12': [0.015, 3],
    '13': [0.014, 3],
    '14': [0.014, 3],
    '15': [0.013, 3],
  }[str(zoom_level)]

  reduced_df = reduce_dataset(df, pd.DataFrame({
    'world_x': pd.Series(dtype='float64'),
    'world_y': pd.Series(dtype='float64'),
    'weight': pd.Series(dtype='float64'),
  }), min_size, min_count)

  print(f'Dataset reduced (min_size={min_size}, min_count={min_count}): {len(df)} -> {len(reduced_df)}')

  # Create buckets & colors
  COLORS = 7
  buckets = create_buckets(reduced_df['weight'].quantile(0.01), reduced_df['weight'].quantile(0.95), COLORS)
  print('Buckets:', buckets)
  colors = create_color_map(PALETTE, len(buckets) + 1)

  # Save legend item
  legends.append({
    'zoom': zoom_level,
    'bounds': [[min_tile_x, min_tile_y], [max_tile_x, max_tile_y]],
    'buckets': list(zip(buckets + [0], colors)),
  })
  legend_path = 'tiles/legend.js'
  os.makedirs(os.path.dirname(legend_path), exist_ok=True)
  legend_file = open(legend_path, 'w')
  legend_file.write(f'var LEGEND = {json.dumps(legends)}')
  legend_file.close()

  print(f'Processing {len(tiles)} tiles...')

  pool = Pool(processes)
  pool.map(process_tile, list(tiles))
  pool.terminate()
