import time
import os
from valis import registration
import _pickle as cPickle
import numba
# from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
# import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
#9-30-22
# comb_folders = [
#                 # 'S22-20908_HEnIF',
#                 # 'S22-20903_HEnIF',
#                 # 'OS22-09541_HEnIF',
#                 # 'S22-21237_HEnIF',
#                 # 'S22-19892_HEnIF',
#                 # 'S22-20626_HEnIF',
#                 # 'S22-23380_HEnIF',
#                 # 'OS22-09539_HEnIF',
#                 # 'S22-21890_HEnIF',
#                 # 'S22-23643_HEnIF',
#                 # 'S22-19912_HEnIF',
#                 # 'S22-20246_HEnIF',
#                 # 'S22-20817_HEnIF',
#                 # 'S22-20815_HEnIF',
#                 # 'S22-22534_HEnIF',
#                 # 'S22-20914_HEnIF',
#                 # 'S22-21024_HEnIF',
#                 # 'S22-19911_HEnIF',
#                 # 'S22-20904_HEnIF',
#                 # 'S22-21383_HEnIF',
#                 # 'OS22-10536_HEnIF',
#                 # 'OS22-10651_HEnIF',
#                 # 'S22-20550_HEnIF',
#                 # 'S22-20697_HEnIF',
#                 # 'S22-09773_HEnIF',
#                 # 'S22-21560_HEnIF',
#                 # 'S22-22036_HEnIF',
#                 # 'S22-21770_HEnIF',
#                 # 'S22-21224_HEnIF',
#                 # 'S22-23689_HEnIF',
#                 # 'S22-19910_HEnIF',
#                 # 'OS22-09371_HEnIF',
#                 # 'S22-21304_HEnIF',
#                 # 'S22-21803_HEnIF',
#                 'S22-21888_HEnIF',
#                 'S22-23119_HEnIF',
#                 'S22-20613_HEnIF',
#                 'S22-22206_HEnIF',
#                 'OS22-09780_HEnIF',
#                 'S22-22413_HEnIF',
#                 'S22-19983_HEnIF',
#                 'S22-21678_HEnIF',
#                 'S22-22201_HEnIF',
#                 'S22-22978_HEnIF',
#                 'S22-20113_HEnIF',
#                 'S22-20518_HEnIF',
#                 'S22-20288_HEnIF'
# ]
# main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/combined"

# #10-05-22
# comb_folders = [
#     # 'S22-23117_HEnIF',
#     # 'S22-24971_HEnIF',
#     # 'S22-24622_HEnIF',
#     'S22-22600_HEnIF',
#     'S22-22955_HEnIF',
#     'S22-22827_HEnIF',
#     'S22-24658_HEnIF',
#     'S22-24099_HEnIF',
#     'S22-24970_HEnIF',
#     'S22-23088_2_HEnIF',
#     'S22-24508_HEnIF',
#     'S22-23088_1_HEnIF',
#     'OS22-11142_HEnIF',
#     'S22-24779_HEnIF',
#     'S22-24904_HEnIF',
#     'S22-24934_HEnIF',
#     'S22-24124_HEnIF'
# ]
#
# main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-05-22/combined"

#10-13-22
comb_folders = [
    # 'S22-25075_HEnIF',
    # 'OS22-11177_HEnIF',
    # 'S22-23753_HEnIF',
    # 'OS22-10840_HEnIF',
    # 'S22-24432_HEnIF',
    # 'S22-25485_HEnIF',
    # 'S22-25712_HEnIF',
    # 'OS22-11607_HEnIF',
    # 'S22-25185_HEnIF',
    # 'S22-24278_HEnIF',
    'S22-25622_HEnIF',
    'OS22-11569_HEnIF',
    'S22-26160_HEnIF',
    'S22-25583_HEnIF',
    'S22-25382_HEnIF',
    'OS22-11417_HEnIF',
    'S22-25342_HEnIF',
    'OS22-11331_HEnIF'
]

main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-13-22/combined"

#10-17-22
# comb_folders = [
#     'S22-26211_HEnIF',
#     'S22-26192_HEnIF',
#     'X22-04096_HEnIF',
#     'S22-25715_HEnIF',
#     'S22-26424_HEnIF',
#     'X22-04209_HEnIF'
# ]
#
# main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-17-22/combined"

# # #11-04-22
# # comb_folders = [
# #     'S22-26787_HEnIF',
# #     'OS22-12068_HEnIF',
# #     'S22-26752_HEnIF',
# #     'OS22-11879_HEnIF',
# #     'S22-26608_HEnIF',
# #     'SB22-15618_HEnIF',
# #     'S22-27115_HEnIF',
# #     'S22-26710_HEnIF',
# #     'S22-26568_HEnIF'
# # ]
# # main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/11-04-22/combined"
# #
# # # #11-14-22
# # comb_folders = [
# #     # 'S22-27249_HEnIF',
# #     # 'S22-27431_HEnIF',
# #     # 'S22-27412_HEnIF',
# #     # 'S22-27673_HEnIF',
# #     # 'S22-27569_HEnIF',
# #     'S22-27506_HEnIF',
# #     'S22-27569_2_HEnIF',
# #     'S22-27798_HEnIF',
# #     'S22-27255_HEnIF'
# # ]
# # main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/11-14-22/combined"
#
# # #12-12-22
# # comb_folders = [
# #     # 'S22-30044_HEnIF',
# #     # 'S22-27802_HEnIF',
# #     # 'S22-28580_HEnIF',
# #     # 'OS22-12583_HEnIF',
# #     # 'S22-27942_HEnIF',
# #     # 'S22-27738_HEnIF',
# #     # 'S22-28869_HEnIF',
# #     # 'S22-28181_HEnIF',
# #     # 'S22-28615_HEnIF',
# #     # 'S22-28316_HEnIF',
# #     # 'S22-28313_HEnIF',
# #     # 'S22-29060_HEnIF',
# #     # 'S22-30065_HEnIF',
# #     # 'S22-29000_HEnIF',
# #     # 'S22-29023_HEnIF',
# #     # 'S22-29027_HEnIF',
# #     # 'OS22-13043_HEnIF',
# #     # 'S22-29219_HEnIF',
# #     # 'S22-29147_HEnIF',
# #     # 'S22-29292_HEnIF',
# #     # 'S22-28934_HEnIF',
# #     'S22-28070_HEnIF'
# # ]
# # main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/12-12-22/combined"
#
# #12-14-22
# # comb_folders = [
# #     # 'S22-30899_HEnIF',
# #     # 'OS22-13385_HEnIF',
# #     # 'OS22-13503_HEnIF',
# #     # 'S22-30390_HEnIF',
# #     # 'S22-31171_HEnIF',
# #     # 'S22-30353_HEnIF',
# #     # 'S22-30466_HEnIF',
# #     # 'S22-31577_HEnIF',
# #     # 'S22-29830_HEnIF',
# #     # 'S22-30388_HEnIF',
# #     # 'S22-30942_HEnIF',
# #     # 'S22-30762_HEnIF',
# #     # 'S22-30525_HEnIF',
# #     # 'S22-29716_HEnIF',
# #     # 'S22-31048_HEnIF',
# #     # 'S22-31084_HEnIF',
# #     # 'S22-29647_HEnIF',
# #     # 'S22-29836_HEnIF',
# #     # 'S22-31457_HEnIF',
# #     'S22-30601_HEnIF',
# #     'OS22-13515_HEnIF',
# #     'S22-29851_HEnIF',
# #     'OS22-14208_HEnIF'
# # ]
# # main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/12-14-22/combined"
#
# # 01-11-23
# # comb_folders = [
# #     # 'S22-31858_HEnIF',
# #     # 'S22-31784_HEnIF',
# #     # 'S22-32477_HEnIF',
# #     # 'OS22-15133_HEnIF',
# #     # 'OS22-14871_2_HEnIF',
# #     # 'S22-31750_HEnIF',
# #     # 'OS22-14957_HEnIF',
# #     # 'S22-33119_HEnIF',
# #     # 'OS22-14871_1_HEnIF',
# #     # 'S22-32427_HEnIF',
# #     # 'S22-32401_HEnIF',
# #     # 'OS22-14882_HEnIF',
# #     # 'S22-31955_HEnIF',
# #     # 'S22-32357_HEnIF',
# #     # 'S22-33180_HEnIF',
# #     # 'S22-31717_HEnIF',
# #     # 'S22-33116_HEnIF',
# #     # 'S22-33408_HEnIF',
# #     # 'S22-32707_HEnIF',
# #     # 'S22-31931_HEnIF',
# #     # 'S22-32394_HEnIF', #### H&E not found
# #     'S22-33177_HEnIF',
# #     'S22-33172_HEnIF',
# #     'S22-32206_HEnIF',
# #     'S22-31720_HEnIF'
# # ]
# # main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/01-11-23/combined"
#
# # 01-19-23
# comb_folders = [
#     # 'S23-00607_HEnIF',
#     # 'S23-00886_HEnIF',
#     # 'S22-33632_HEnIF',
#     # 'S23-00189_HEnIF',
#     'S22-33870_HEnIF',
#     'S22-33726_HEnIF',
#     'S23-00734_HEnIF',
#     'S23-00702_HEnIF',
#     'S23-01000_HEnIF',
#     'S23-00732_HEnIF',
#     'S23-00332_HEnIF',
#     'S23-00542_HEnIF',
#     'S22-33519_HEnIF',
#     'S23-00419_HEnIF',
#     'S23-00733_HEnIF',
#     'S22-33733_HEnIF'
# ]
# main_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/01-19-23/combined"


print("working on {}".format(main_dir))

DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}
# DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}

print(comb_folders)
for cf in comb_folders:
  print("working on {}".format(cf))
  slide_src_dir = os.path.join(main_dir, cf)
  results_dst_dir = os.path.join(main_dir, "expected_results/registration")
  # H&E as reference image
  ref_f = [f for f in os.listdir(os.path.join(main_dir, cf)) if f.endswith(".svs")][0]
  print(ref_f)
  try:
    print("trying to load registrar data from saved pickle file...")
    with open(os.path.join(results_dst_dir, cf, "data", "{}_registrar.pickle".format(cf)), 'rb') as regfile:
      registrar = cPickle.load(regfile)
    print("loading from pickle...")
  except Exception as e:
      # print(e)
      # continue
  # Create a Valis object and use it to register the slides in slide_src_dir
      start = time.time()
      registrar = registration.Valis(slide_src_dir, results_dst_dir,
                                     reference_img_f=ref_f, align_to_reference=True,
                                     # max_image_dim_px=800,
                                     # max_processed_image_dim_px=800,
                                     # max_non_rigid_registartion_dim_px=800
                                     )
      # reader_cls = VipsSlideReader
      rigid_registrar, non_rigid_registrar, error_df = registrar.register(if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS)
      stop = time.time()
      elapsed = stop - start
      print(f"registration time is {elapsed/60} minutes")

  # Check results in registered_slide_dst_dir. If they look good, export the registered slides
  # registered_slide_dst_dir = os.path.join(main_dir, "expected_results/nonrigid_registered_slides", registrar.name)
  registered_slide_dst_dir = os.path.join(main_dir, "expected_results/nonrigid_registered_slides", registrar.name)
  start = time.time()
  registrar.warp_and_save_slides(registered_slide_dst_dir, non_rigid = True, compression='jp2k')
  stop = time.time()
  elapsed = stop - start
  print(f"saving {registrar.size} slides took {elapsed/60} minutes")

# Shutdown the JVM
registration.kill_jvm()