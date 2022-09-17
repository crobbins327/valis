import os
import pyvips
# import valis.slide_io
# import zstd
level = 0
toilet_roll = pyvips.Image.new_from_file(os.path.join('G:/My Drive/AQUA-QuPath/Test1 515 array/Test1@20220804_185225_161578.ome.tiff'), n=-1, subifd=level-1)
# toilet_roll.get_fields()
# toilet_roll.get('image-description')
# toilet_roll.get('vips-loader')
# compression_type = 'jp2k'
# compression_type = 'zstd'
# compression_type = 'webp'
compression_type = 'deflate'
# compression_type = 'lzw'
# -7 (fastest) to 22 (slowest but best compression ratio)
zstd_level = 11
# Q = 100
toilet_roll.tiffsave(os.path.join('G:/My Drive/AQUA-QuPath/Test1 515 array', 'test1_{}.ome.tiff'.format(compression_type)),
                     compression=compression_type,
	                 # Q=100,
                     # level=zstd_level,
                     # lossless = True,
                     tile=True, tile_width=1024, tile_height=1024,
                     pyramid=True, subifd=True,
                     bigtiff=True, rgbjpeg=False)