import pyvips
import json
import pandas as pd
import numpy as np
import os
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
# from valis.slide_io import VipsSlideReader, BioFormatsSlideReader, get_slide_reader

aligned_IF_folders =[]
if_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/combined/expected_results/nonrigid_registered_slides"
image_path = os.path.join(if_dir, "OS22-09371-13[zXS22-296]@20221001_234925_924179_deflate_Hflip.ome.tiff")

# Can read entire image as multiband vips image quickly using vips
# reader_cls = get_slide_reader(image_path, series=None)
# valis_slide = reader_cls(image_path)
# vips_slide = valis_slide.slide2vips(level=2)

# micron per pixel resolution
MPP = 0.325
# in ms
exp_time = 5
bitrange = 2**16
norm_factor = (exp_time/1000)*(MPP**2)*bitrange
level = 2
channel = 3
# select 3rd channel
channel_img = pyvips.Image.new_from_file(image_path, page=channel-1, subifd=level-1)
# probably don't need double precision for this problem... will save on storage
channel_img = channel_img.cast("float")
# plt.imshow(channel_img)
# normalize by factors
channel_img = channel_img / norm_factor
# normalize with HER2 515 standard curve to ~ HER2 amol/mm2
channel_img = channel_img.linear(0.05864298562220563, 0.669873552472741)
channel_img = channel_img.copy(interpretation="b-w")
# slight gaussian blur?
# blur_img = channel_img.gaussblur(5, precision="float")
# bin pixel values into categories
mask = np.zeros((channel_img.height, channel_img.width))
channel_array = np.array(channel_img)
mask[np.logical_and(channel_array >= 3, channel_array < 9)] = 1
mask[np.logical_and(channel_array >= 9, channel_array < 23)] = 2
mask[np.logical_and(channel_array >= 23, channel_array < 40)] = 3
mask[channel_array >= 40] = 4

from PIL import Image
mask = Image.fromarray(mask.astype('uint8'), 'P')
color_palette = [255,255,255,
                 0,0,255,
                 0,100,0,
                 0,100,0,
                 255,0,0]
mask.putpalette(color_palette)
plt.imshow(mask)
# only pull out pixels inside CK binary mask...


# fill holes...


c_x = int(channel_img.width/2)
c_y = int(channel_img.height/2)
patch_size = 5000
plt.figure(1)
plt.imshow(channel_img.crop(c_x-patch_size, c_y-patch_size, patch_size, patch_size))
plt.figure(2)
plt.imshow(blur_img.crop(c_x-patch_size, c_y-patch_size, patch_size, patch_size))


crop_img = channel_img.crop(c_x-patch_size, c_y-patch_size, patch_size, patch_size)
jj = np.array(crop_img)



# Images are too big to save..... 3GB for one channel, no pyramiding...
# output.set_type(pyvips.GValue.gstr_type, "interpretation", "rgb")
channel_img.set_type(pyvips.GValue.gint_type, "page-height", channel_img.height)
channel_img.set_type(pyvips.GValue.gstr_type, "image-description",
                f"""<?xml version="1.0" encoding="UTF-8"?>
            <OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
            <Instrument ID="Instrument:0">
                <Objective ID="Objective:0" NominalMagnification="20.0"/>
            </Instrument>
            <Image ID="Image:0">
                <InstrumentRef ID="Instrument:0"/>
                <ObjectiveSettings ID="Objective:0"/>
                <Pixels DimensionOrder="XYCZT"
                        ID="Pixels:0"
                        PhysicalSizeX="0.325"
                        PhysicalSizeXUnit="µm" 
                        PhysicalSizeY="0.325" 
                        PhysicalSizeYUnit="µm" 
                        PhysicalSizeZ="0.7787" 
                        PhysicalSizeZUnit="µm" 
                        SizeC="{1}"
                        SizeT="1"
                        SizeX="{channel_img.width}"
                        SizeY="{channel_img.height}"
                        SizeZ="1"
                        Type="float">
                        <Channel ID="Channel:0:0" SamplesPerPixel="1">
                            <LightPath/>
                        </Channel>
                </Pixels>
            </Image>
        </OME>""")
output_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/"
channel_img.tiffsave(os.path.join(output_dir, "test.ome.tiff"),
                compression="jp2k",
                Q=100,
                # level=zstd_level,
                # lossless=True,
                tile=True, tile_width=1024, tile_height=1024,
                pyramid=False, subifd=False,
                bigtiff=True
                )





