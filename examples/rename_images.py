import os

# rename images based on compression/values after alignment/registration
# idDF = pd.read_excel(r"E:\HS-HER2 Images\RareCyte-HS-HER2\Serial_sections\HS-HER2 serial section barcodes.xlsx")
# proj_dir = r"G:\My Drive\Yale-QIF-HER2\SerialSection_IntraAssay_RCyte\5ms"
#res_dir = r"G:\My Drive\Yale-QIF-HER2\SerialSection_IntraAssay_RCyte\5ms\expected_results\nonrigid_registered_slides"
res_dir = "/home/cjr66/scratch60/HS-HER2/expected_results/nonrigid_registered_slides/"
res_folders = [f for f in os.listdir(res_dir) if not f.endswith("_deflate")]
print(res_folders)
for f in res_folders:
	ome_files = [i for i in os.listdir(os.path.join(res_dir, f)) if i.endswith(".ome.tiff")]
	for o in ome_files:
		if not o.endswith("_jp2k.ome.tiff"):
			newName = o.rsplit(".ome.tiff", 1)[0].rsplit("_deflate", 1)[0] + "_jp2k.ome.tiff"
			print("renaming {} to {}".format(o, newName))
			os.rename(os.path.join(os.path.join(res_dir, f, o)), os.path.join(res_dir, f, newName))
		else:
			print("skipping {}".format(o))

