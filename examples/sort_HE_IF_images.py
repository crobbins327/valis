import os
import pandas as pd
import re
import numpy as np
import shutil

# Sort HE and IF images into a combined folder
# idDF = pd.read_excel("/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-05-22/HS-HER2 Prospective 10-05-22.xlsx", sheet_name=2)
idDF = pd.read_excel("/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/HS-HER2 prospective & premalig IDs 9-30-22.xlsx", sheet_name=1)
idDF = idDF.dropna(axis=0, subset="Outside Slide Desig.")

proj_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/combined"
IF_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/IF"
HE_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/H&E"
# figure out what folder names should be from DF
def get_foldername(filename):
	if re.match("^515", filename):
		return "515_standards"
	else:
		return "{}_HEnIF".format(filename.rsplit("_", 1)[0])

def re_rsplit(pattern, text, maxsplit):
    if maxsplit < 1 or not pattern.search(text): # If split is 0 or less, or upon no match
        return [text]                            # Return the string itself as a one-item list
    prev = len(text)                             # Previous match value start position
    cnt = 0                                      # A match counter
    result = []                                  # Output list
    for m in reversed(list(pattern.finditer(text))):
        result.append(text[m.end():prev])        # Append a match to resulting list
        prev = m.start()                         # Set previous match start position
        cnt += 1                                 # Increment counter
        if cnt == maxsplit:                      # Break out of for loop if...
            break                                # ...match count equals max split value
    result.append(text[:prev])                   # Append the text chunk from start
    return reversed(result)                      # Return reversed list

idDF["Folders"] = idDF["Outside Slide Desig."].apply(lambda i: get_foldername(i))
# create folders
folders_to_create = np.unique(idDF["Folders"])
for f in folders_to_create:
	os.makedirs(os.path.join(proj_dir, f), exist_ok=True)

IF_ome_files = [i for i in os.listdir(IF_dir) if i.endswith(".ome.tiff")]
HE_files = [i for i in os.listdir(HE_dir) if i.endswith(".svs")]

# move files according to id -> surg_path -> folder in idDF
folders_to_scan = os.listdir(proj_dir)
for f in folders_to_scan:
	folder = f.rsplit("_HEnIF", 1)[0]
	if re.match("^515", folder):
		folder = "515"
	folder_id_parts = list(re_rsplit(re.compile(r"-|_"), folder, 1))
	HE_f = [s for s in HE_files if re.search("^{}".format("-".join(folder_id_parts[:2])), s)]
	IF_f = [o for o in IF_ome_files if re.search("^{}".format(folder), o)]
	if not HE_f and not IF_f:
		print("no files found for folder {}".format(f))
		print("skipping...")
		continue
	for h in HE_f:
		print("moving {} to {}".format(h, f))
		if not os.path.exists(os.path.join(proj_dir, f, h)):
			# move file to new destination folder
			shutil.move(os.path.join(HE_dir, h),
						os.path.join(proj_dir, f, h))
	for j in IF_f:
		print("moving {} to {}".format(j, f))
		if not os.path.exists(os.path.join(proj_dir, f, j)):
			# move file to new destination folder
			shutil.move(os.path.join(IF_dir, j),
						os.path.join(proj_dir, f, j))



