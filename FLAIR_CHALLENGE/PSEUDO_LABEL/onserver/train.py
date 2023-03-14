import os
import torch
import torchvision
import dataloader

assert torch.cuda.is_available()


print("load data")
dataset = dataloader.FLAIR("/scratchf/CHALLENGE_IGN/test/")

print("define model")
net = torch.load("../baseline/build/model.pth")
net = net.cuda()
net.eval()

net0 = torch.load("../baseline/build/model.pth")
net0 = net0.cuda()
net0.eval()


print("train")


def crossentropy(y, z):
    class_weights = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
    tmp = torch.nn.CrossEntropyLoss(weight=torch.Tensor(class_weights).cuda())
    return tmp(z, y.long())


def dicelossi(y, z, i):
    eps = 0.001
    z = z.softmax(dim=1)

    indexmap = torch.ones(z.shape).cuda()
    indexmap[:, i, :, :] = 0

    z0, z1 = z[:, i, :, :], (z * indexmap).sum(1)
    y0, y1 = (y == i).float(), (y != i).float()

    inter0, inter1 = (y0 * z0).sum(), (y1 * z1).sum()
    union0, union1 = (y0 + z1 * y0).sum(), (y1 + z0 * y1).sum()

    if union0 < eps or union1 < eps or union0 < inter0 or union1 < inter1:
        return 0

    iou0, iou1 = (inter0 + eps) / (union0 + eps), (inter1 + eps) / (union1 + eps)
    iou = 0.5 * (iou0 + iou1)
    return 1 - iou


def diceloss(y, z):
    alldice = torch.zeros(12).cuda()
    for i in range(12):
        alldice[i] = dicelossi(y, z, i)
    return alldice.mean()


params = [
    net.final1.weight,
    net.final1.bias,
    net.final2.weight,
    net.final2.bias,
    net.final3.weight,
    net.final3.bias,
    net.classif.weight,
    net.classif.bias,
]
optimizer = torch.optim.Adam(params, lr=0.00000001)
printloss = torch.zeros(1).cuda()
stats = torch.zeros((13, 13)).cuda()
batchsize = 32
nbbatchs = 5000
dataset.start()

K = 64

for i in range(nbbatchs):
    x = dataset.getBatch(batchsize)
    x = x.cuda()

    with torch.no_grad():
        z = net0(x)
        v, py = z.max(1)
        for j in range(12):
            l = (v * (py == j).float()).flatten()
            l, _ = l.sort()
            if l[-K] <= 0:
                seuil = 100
            else:
                seuil = l[-K]

            v = v * (py != j).float() + (py == j).float() * (v > seuil).float()

        py = py * (v > 0).float() + 12 * (v <= 0).float()

    z = net(x)
    ce = crossentropy(py, z)
    dice = diceloss(py, z)
    loss = ce + dice

    with torch.no_grad():
        printloss += loss.clone().detach()

        if i < 10:
            print(i, "/", nbbatchs, printloss)
        if i < 1000 and i % 100 == 99:
            print(i, "/", nbbatchs, printloss / 100)
            printloss = torch.zeros(1).cuda()
        if i >= 1000 and i % 300 == 299:
            print(i, "/", nbbatchs, printloss / 300)
            printloss = torch.zeros(1).cuda()

        if i % 1000 == 999:
            torch.save(net, "build/model.pth")

    if i > nbbatchs * 0.1:
        loss = loss * 0.7
    if i > nbbatchs * 0.2:
        loss = loss * 0.7
    if i > nbbatchs * 0.5:
        loss = loss * 0.7
    if i > nbbatchs * 0.8:
        loss = loss * 0.7

    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), 1)
    optimizer.step()

torch.save(net, "build/model4.pth")
os._exit(0)
