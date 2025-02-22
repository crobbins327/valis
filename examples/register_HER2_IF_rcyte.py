import time
import os
from valis import registration
import _pickle as cPickle
from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
# import matplotlib
# matplotlib.use('TkAgg')
# import matplotlib.pyplot as plt


# slide_src_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/extra/S18_21762-IHC0"
# results_dst_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/expected_results/registration"

serial_folders = [
                # 'S18_26442_0_all',
                # 'S18_28210_2_all',
                'S18_31022_2_all',
                'S19_08281_1_all',
                'S19_09265_2N_all',
                'S19_09851_0_all'
                # 'S20_15425_all',
                # 'S20_18310_0_all',
                # 'S20_21308_all',
                # 'S20_22015_all',
                # 'S20_25677_all',
                # 'S20_25771_all'
                  ]
#main_dir = "G:/My Drive/Yale-QIF-HER2/SerialSection_IntraAssay_RCyte/5ms"
main_dir = "/home/cjr66/scratch60/HS-HER2"
DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}

for cf in serial_folders:
  print("working on {}".format(cf))
  slide_src_dir = os.path.join(main_dir, cf)
  results_dst_dir = os.path.join(main_dir, "expected_results/registration")


  # try:
  #   print("trying to load registrar data from saved pickle file...")
  #   with open(os.path.join(results_dst_dir, cf, "data", "{}_registrar.pickle".format(cf)), 'rb') as regfile:
  #     registrar = cPickle.load(regfile)
  #   print("loading from pickle...")
  # except:
  # Create a Valis object and use it to register the slides in slide_src_dir
  start = time.time()
  registrar = registration.Valis(slide_src_dir, results_dst_dir, imgs_ordered=True)
  # reader_cls = VipsSlideReader
  rigid_registrar, non_rigid_registrar, error_df = registrar.register(if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS)
  stop = time.time()
  elapsed = stop - start
  print("regisration time is {} minutes".format(elapsed/60))

  # Check results in registered_slide_dst_dir. If they look good, export the registered slides
  registered_slide_dst_dir = os.path.join(main_dir, "expected_results/nonrigid_registered_slides", registrar.name)
  # registered_slide_dst_dir = os.path.join(main_dir, "expected_results/rigid_registered_slides", registrar.name)
  start = time.time()
  registrar.warp_and_save_slides(registered_slide_dst_dir, non_rigid = True, perceputally_uniform_channel_colors=True, compression='jp2k')
  stop = time.time()
  elapsed = stop - start
  print("saving {} slides took {} minutes".format(registrar.size, elapsed/60))



# Shutdown the JVM
registration.kill_jvm()
