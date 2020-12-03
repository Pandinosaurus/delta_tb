

import sys
print(sys.argv)
assert(len(sys.argv)>1)

import numpy as np
import PIL
from PIL import Image
from sklearn.metrics import confusion_matrix

import torch
import torch.backends.cudnn as cudnn
device = "cuda" if torch.cuda.is_available() else "cpu"
if device == "cuda":
    torch.cuda.empty_cache()
    cudnn.benchmark = True

sys.path.append('..')
import segsemdata



print("load data")
class MergedSegSemDataset:
    def __init__(self,alldatasets):
        self.alldatasets = alldatasets
        self.colorweights=[]
        
    def getrandomtiles(self,nbtiles,tilesize,batchsize):
        XY = []
        for dataset in self.alldatasets:
            xy = dataset.getrawrandomtiles((nbtiles//len(self.alldatasets))+1,tilesize)
            XY = x+y
        
        X = torch.stack([torch.Tensor(np.transpose(x,axes=(2, 0, 1))).cpu() for x,y in XY])
        Y = torch.stack([torch.from_numpy(y).long().cpu() for x,y in XY])
        dataset = torch.utils.data.TensorDataset(X,Y)
        dataloader = torch.utils.data.DataLoader(dataset, batch_size=batchsize, shuffle=True, num_workers=2)

        return dataloader
        
    def getCriterionWeight(self):
        return self.colorweights.copy()   

root = "/data/"
alldatasets = []

for i in range(1,len(sys.argv)):
    assert(sys.argv[i].find('_')>0)
    name = sys.argv[i].find('_')
    mode = sys.argv[i][name+1:]
    name = sys.argv[i][:name]
    assert(name in ["VAIHINGEN","POTSDAM","BRUGES","TOULOUSE","AIRS"])
    assert(mode in ["test","all"])

    if name == "VAIHINGEN":
        data = segsemdata.makeISPRS(datasetpath = root+"ISPRS_VAIHINGEN", labelflag="lod0",weightflag="iou",dataflag=mode,POTSDAM=False)
    if name == "POTSDAM":
        data = segsemdata.makeISPRS(datasetpath = root+"ISPRS_POTSDAM", labelflag="lod0",weightflag="iou",dataflag=mode,POTSDAM=True)
    if name == "BRUGES":
        data = segsemdata.makeDFC2015(datasetpath = root+"DFC2015", labelflag="lod0",weightflag="iou",dataflag=mode)
    if name == "TOULOUSE":
        data = segsemdata.makeSEMCITY(datasetpath = root+"SEMCITY_TOULOUSE",dataflag=mode, labelflag="lod0",weightflag="iou") 
    if name == "AIRS":
        data = segsemdata.makeAIRSdataset(datasetpath = root+"AIRS",dataflag=mode,weightflag="iou")  
  
    alldatasets.append(data.copyTOcache(outputresolution=50,color=False,normalize=True))
    
nbclasses = 2
cm = np.zeros((nbclasses,nbclasses),dtype=int)

data = MergedSegSemDataset(alldatasets)



print("load unet")
import unet
with torch.no_grad():
    net = torch.load("build/model.pth")
    net = net.to(device)



print("test")
with torch.no_grad():
    net.eval()
    for data in alldatasets:
        for name in data.getnames():
            image,label = data.getImageAndLabel(name,innumpy=False)
            pred = net(image.to(device))
            _,pred = torch.max(pred[0],0)
            pred = pred.cpu().numpy()

            assert(label.shape==pred.shape)

            cm+= confusion_matrix(label.flatten(),pred.flatten(),list(range(nbclasses)))

            pred = PIL.Image.fromarray(data.vtTOcolorvt(pred))
            pred.save("build/"+name+"_z.png")

        print(getstat(cm))
        print(cm)

