import os
import json
import numpy
import torch


def number6(i):
    s = str(i)
    while len(s) < 6:
        s = "0" + s
    return s


root = "/scratchf/CHALLENGE_IGN/FLAIR_2/"

with open(root + "flair-2_centroids_sp_to_patch.json") as fichier:
    coords = json.load(fichier)

    tmp = min([v[0] for (_,v) in coords.items()])
    print(tmp)
    tmp = min([v[1] for (_,v) in coords.items()])
    print(tmp)
    tmp = max([v[0] for (_,v) in coords.items()])
    print(tmp)
    tmp = max([v[1] for (_,v) in coords.items()])
    print(tmp)

    coords = {key: coords[key] for key in sorted(coords.keys())}
checkforget = set(coords.keys())

trainpaths = {}
trainfolder, trainsubfolder = os.listdir(root + "flair_aerial_train/"), []
for folder in trainfolder:
    subfolder = os.listdir(root + "flair_aerial_train/" + folder)
    trainsubfolder += [(folder + "/" + sub) for sub in subfolder]

for tmp in coords:
    num = int(tmp[4:-4])

    for folder in trainsubfolder:
        tmp = "flair_aerial_train/" + folder + "/img/IMG_"
        if os.path.exists(root + tmp + number6(num) + ".tif"):
            trainpaths[num] = {}
            checkforget.remove("IMG_" + number6(num) + ".tif")
            trainpaths[num]["image"] = tmp + number6(num) + ".tif"
            tmp = "flair_labels_train/" + folder + "/msk/MSK_"
            trainpaths[num]["label"] = tmp + number6(num) + ".tif"
            assert os.path.exists(root + trainpaths[num]["label"])

            tmp = "flair_sen_train/" + folder + "/sen/"
            l = os.listdir(root + tmp)

            l = [s for s in l if "data.npy" in s]
            assert len(l) == 1
            trainpaths[num]["sen"] = tmp + l[0]

            a, b = coords["IMG_" + number6(num) + ".tif"]
            assert 20 <= a <= 186 and 20 <= b <= 186
            trainpaths[num]["coord"] = (a - 20, b - 20)

torch.save(trainpaths, root + "alltrainpaths.pth")

print("THE SAME WITH TEST !!!!!!!!")
trainpaths = {}
trainfolder, trainsubfolder = os.listdir(root + "flair_2_aerial_test/"), []
for folder in trainfolder:
    subfolder = os.listdir(root + "flair_2_aerial_test/" + folder)
    trainsubfolder += [(folder + "/" + sub) for sub in subfolder]

for tmp in coords:
    num = int(tmp[4:-4])

    for folder in trainsubfolder:
        tmp = "flair_2_aerial_test/" + folder + "/img/IMG_"
        if os.path.exists(root + tmp + number6(num) + ".tif"):
            trainpaths[num] = {}
            checkforget.remove("IMG_" + number6(num) + ".tif")
            trainpaths[num]["image"] = tmp + number6(num) + ".tif"

            tmp = "flair_2_sen_test/" + folder + "/sen/"
            l = os.listdir(root + tmp)

            l = [s for s in l if "data.npy" in s]
            assert len(l) == 1
            trainpaths[num]["sen"] = tmp + l[0]

            a, b = coords["IMG_" + number6(num) + ".tif"]
            assert 20 <= a <= 186 and 20 <= b <= 186
            trainpaths[num]["coord"] = (a - 20, b - 20)

torch.save(trainpaths, root + "alltestpaths.pth")

print("checkforget", checkforget)
