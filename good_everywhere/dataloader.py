import numpy
import os
import PIL
from PIL import Image
import torch
import random
import cropextractor


def distancetransform(y, size=4):
    yy = 2.0 * y.unsqueeze(0) - 1
    yyy = torch.nn.functional.avg_pool2d(
        yy, kernel_size=2 * size + 1, stride=1, padding=size
    )
    D = 1.0 - 0.5 * (yy - yyy).abs()
    return D[0]


class MiniWorld:
    def __init__(self, flag, custom=None, tilesize=128):
        assert flag in ["train", "test", "custom"]

        self.cities = [
            "potsdam",
            "christchurch",
            "toulouse",
            "austin",
            "chicago",
            "kitsap",
            "tyrol-w",
            "vienna",
            "bruges",
            "Arlington",
            "Austin",
            "DC",
            "NewYork",
            "SanFrancisco",
            "Atlanta",
            "NewHaven",
            "Norfolk",
            "Seekonk",
        ]
        self.tilesize = tilesize

        if flag == "custom":
            self.cities = custom
        else:
            if flag == "train":
                self.cities = [s + "/train/" for s in self.cities]
            else:
                self.cities = [s + "/test/" for s in self.cities]

        whereIam = os.uname()[1]
        if whereIam in ["super", "wdtim719z"]:
            self.root = "/data/miniworld/"
        if whereIam == "ldtis706z":
            self.root = "/media/achanhon/bigdata/data/miniworld/"
        if whereIam in ["calculon", "astroboy", "flexo", "bender"]:
            self.root = "/scratch_ai4geo/miniworld/"

        self.data = {}
        for city in self.cities:
            self.data[city] = cropextractor.CropExtractor(
                self.root + city, tilesize=tilesize
            )
        self.run = False

    def start():
        self.run = True
        for city in self.cities:
            self.data[city].start()

    def getbatch(self, batchsize, batchpriority=None):
        assert self.run
        assert batchpriority is None or numpy.sum(batchpriority) > 0

        tilesize = self.tilesize
        if batchpriority is None:
            batchpriority = numpy.ones(self.cities)
        batchpriority /= numpy.sum(batchpriority)

        batchchoice = numpy.random.choice(len(self.cities), batchsize, p=batchpriority)

        x = torch.zeros(batchsize, 3, tilesize, tilesize)
        y = torch.zeros(batchsize, tilesize, tilesize)
        for i in batchchoice:
            x[i], y[i] = self.data[self.cities[i]].getcrop()
        return x, y, batchchoice
