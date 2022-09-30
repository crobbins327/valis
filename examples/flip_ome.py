import os
import pyvips
# import valis.slide_io
# import zstd
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

img_dir = r"G:\My Drive\Yale-QIF-HER2\WTSVal_RCyte\5ms_HS-HER2_WTSVal\S20_27517_HEnIF"
img_f = "zXS22-2D186@20220917_015459_420982_deflate.ome.tiff"
level = 0
toilet_roll = pyvips.Image.new_from_file(os.path.join(img_dir, img_f), n=-1, subifd=level-1)
toilet_roll = toilet_roll.fliphor()
# toilet_roll.get_fields()
# toilet_roll.get('image-description')
# toilet_roll.get('vips-loader')
compression_type = 'jp2k'
new_f = "{}_{}.ome.tiff".format(img_f.rsplit("_deflate", 1)[0], compression_type)
# compression_type = 'zstd'
# compression_type = 'webp'
# compression_type = 'deflate'
# compression_type = 'lzw'
# -7 (fastest) to 22 (slowest but best compression ratio)
# zstd_level = 11
# Q = 100
toilet_roll.tiffsave(os.path.join(img_dir, new_f),
                     compression=compression_type,
	                 Q=100,
                     # level=zstd_level,
                     # lossless = True,
                     tile=True, tile_width=1024, tile_height=1024,
                     pyramid=True, subifd=True,
                     bigtiff=True, rgbjpeg=False)