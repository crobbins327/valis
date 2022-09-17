import os
import pandas as pd
import re
import numpy as np
import shutil

# Sort rarecyte images into serial section folders for image registration
idDF = pd.read_excel(r"E:\HS-HER2 Images\RareCyte-HS-HER2\Serial_sections\HS-HER2 serial section barcodes.xlsx")
proj_dir = r"G:\My Drive\Yale-QIF-HER2\SerialSection_IntraAssay_RCyte\5ms"
# figure out what folder names should be from DF
def get_foldername(filename):
	if re.match("^515", filename):
		return "515_standards"
	elif re.search("T[0-9].E[0-9]$", filename):
		split_name = filename.rsplit("T", 1)[0][:-1]
		return "{}_all".format(split_name)
	else:
		split_name = filename.rsplit("E", 1)[0][:-1]
		# print(split_name)
		return "{}_all".format(split_name)

idDF["Folders"] = idDF["Outside Slide Desig."].apply(lambda i: get_foldername(i))
# create folders
folders_to_create = np.unique(idDF["Folders"])
for f in folders_to_create:
	os.makedirs(os.path.join(proj_dir, f))

ome_files = [i for i in os.listdir(proj_dir) if i.endswith(".ome.tiff")]

# move files according to id -> surg_path -> folder in idDF
for o in ome_files:
	# split ridiculous name for rarecyte images....
	oID = o.split("@")[0].replace("-2D", "-")
	dst_folder = idDF[idDF["Yale Case No."] == oID]["Folders"].values[0]
	if not os.path.exists(os.path.join(proj_dir, dst_folder, o)):
		# move file to new destination folder
		shutil.move(os.path.join(proj_dir, o),
		            os.path.join(proj_dir, dst_folder, o))

