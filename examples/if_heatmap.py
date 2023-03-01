import pyvips
import json
import pandas as pd
import numpy as np
import os
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

from valis.slide_io import VipsSlideReader, BioFormatsSlideReader

aligned_IF_folders =[]
if_dir = r"G:\My Drive\Yale-QIF-HER2\HS-HER2 Prospective\9-30-22\aligned\nonrigid_registered_slides"
image_path = os.path.join(if_dir, "OS22-09371-13[zXS22-296]@20221001_234925_924179_deflate_Hflip.ome.tiff")

