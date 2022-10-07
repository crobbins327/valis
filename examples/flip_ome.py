import os
import pyvips
# import valis.slide_io
# import zstd
# import matplotlib
# matplotlib.use('TkAgg')
# import matplotlib.pyplot as plt
import logging
import re
import time
import datetime
import multiprocessing as mp


def flip_images(img_dir, img_f, compression_type = "deflate", level = 0):
    toilet_roll = pyvips.Image.new_from_file(os.path.join(img_dir, img_f), n=-1, subifd=level - 1)
    toilet_roll = toilet_roll.fliphor()
    # toilet_roll.get_fields()
    # toilet_roll.get('image-description')
    # toilet_roll.get('vips-loader')
    # compression_type = 'jp2k'
    # compression_type = 'zstd'
    # compression_type = 'webp'
    # compression_type = 'deflate'
    # compression_type = 'lzw'
    # -7 (fastest) to 22 (slowest but best compression ratio)
    # zstd_level = 11
    # Q = 100
    new_f = "{}_{}_flipped.ome.tiff".format(img_f.rsplit("_deflate", 1)[0], compression_type)
    print("Saving file:\n{}".format(os.path.join(img_dir, new_f)))
    start = time.time()
    toilet_roll.tiffsave(os.path.join(img_dir, new_f),
                         compression=compression_type,
                         Q=100,
                         # level=zstd_level,
                         # lossless = True,
                         tile=True, tile_width=1024, tile_height=1024,
                         pyramid=True, subifd=True,
                         bigtiff=True, rgbjpeg=False)
    min, sec = divmod(time.time() - start, 60)
    print("compress time {:.0f}min : {:.2f}s".format(min, sec))

if __name__ == '__main__':
    start = time.time()
    num_workers = 8
    # jp2k: num_workers ~ 8 [2 cores for each worker on 16 core CPU] --> ~6min per file [8x --> 45min for 60 files, ~64min for 91 files], compression runs faster when multiple cores are available per worker
    # deflate: num_workers ~ 14 [~1 core each] --> ~3min:30s per file [14x ---> 16 min for 60 files, ~21 min for 79 files], compression can be parallelized with more workers because less cores are needed
    compression_type = "jp2k"
    level = 0

    proj_dir = "/home/cjr66/scratch60/HS-HER2/5ms_HS-HER2_WTSVal"
    folders = os.listdir(proj_dir)

    img_details = []
    for f in folders:
        l = os.listdir(os.path.join(proj_dir, f))
        if any("ome.tif" in s for s in l):
            img_f = [o for o in os.listdir(os.path.join(proj_dir, f)) if o.endswith("_deflate.ome.tiff")][0]
            img_details.append({"image_dir": os.path.join(proj_dir, f),
                                "image_file": img_f})

    # setup compress jobs to run as an iterable

    with mp.Pool(num_workers) as pool:
        # pool = mp.Pool(num_workers)
        iterable = [(d["image_dir"], d["image_file"], compression_type, level) for d in img_details]
        res = pool.starmap(flip_images, iterable)
        pool.close()
        pool.join()

    hms = str(datetime.timedelta(seconds=time.time() - start))
    print(
        "Total time for {} compression of {} images... {} H:min:s".format(compression_type, len(img_details), hms)
    )