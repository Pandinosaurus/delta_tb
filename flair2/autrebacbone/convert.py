import torch, torchvision


class MyNet(torch.nn.Module):
    def __init__(self):
        super(MyNet, self).__init__()
        tmp = torchvision.models.regnet_y_16gf(
            weights=torchvision.models.RegNet_Y_16GF_Weights.IMAGENET1K_V2
        )
        with torch.no_grad():
            old = tmp.stem[0].weight / 2
            tmp.stem[0] = torch.nn.Conv2d(6, 32, kernel_size=3, stride=2, padding=1)
            tmp.stem[0].weight = torch.nn.Parameter(torch.cat([old, old], dim=1))
        del tmp.trunk_output.block4
        del tmp.fc
        self.reg = tmp
        self.classiflow = torch.nn.Conv2d(1232, 13, kernel_size=1)

        ks = (2, 1, 1)
        self.conv1 = torch.nn.Conv3d(10, 32, kernel_size=ks, stride=ks, padding=0)
        self.conv2 = torch.nn.Conv3d(32, 64, kernel_size=ks, stride=ks, padding=0)
        self.conv3 = torch.nn.Conv3d(64, 92, kernel_size=(3, 3, 3))
        self.conv4 = torch.nn.Conv3d(92, 128, kernel_size=ks, stride=ks, padding=0)
        self.conv5 = torch.nn.Conv2d(256, 256, kernel_size=3)
        self.conv6 = torch.nn.Conv2d(256, 256, kernel_size=3)
        self.conv7 = torch.nn.Conv2d(256, 280, kernel_size=3)

        self.merge1 = torch.nn.Conv2d(1512, 512, kernel_size=1)
        self.merge2 = torch.nn.Conv2d(2024, 512, kernel_size=1)
        self.merge3 = torch.nn.Conv2d(2024, 112, kernel_size=1)

        self.decod1 = torch.nn.Conv2d(336, 112, kernel_size=1)
        self.decod2 = torch.nn.Conv2d(448, 112, kernel_size=1)
        self.decod3 = torch.nn.Conv2d(448, 112, kernel_size=3, padding=1)
        self.decod4 = torch.nn.Conv2d(448, 112, kernel_size=3, padding=1)
        self.classif = torch.nn.Conv2d(448, 13, kernel_size=1)

        self.compress = torch.nn.Conv2d(112, 2, kernel_size=1)
        self.expand = torch.nn.Conv2d(2, 64, kernel_size=1)
        self.expand2 = torch.nn.Conv2d(13, 64, kernel_size=1)
        self.generate1 = torch.nn.Conv2d(64, 128, kernel_size=1)
        self.generate2 = torch.nn.Conv2d(128, 32, kernel_size=1)
        self.generate3 = torch.nn.Conv2d(32, 10, kernel_size=1)

        self.lrelu = torch.nn.LeakyReLU(negative_slope=0.1, inplace=False)

    def forwardRGB(self, x):
        x = ((x / 255) - 0.5) / 0.25
        xm = torch.ones(x.shape[0], 1, 512, 512).cuda()
        x = torch.cat([x, xm], dim=1)

        hr = self.reg.trunk_output.block1(self.reg.stem(x))  # 224
        x = self.reg.trunk_output.block3(self.reg.trunk_output.block2(hr))  # 1232
        plow = self.classiflow(x)
        plow = torch.nn.functional.interpolate(plow, size=(512, 512), mode="bilinear")

        return plow, x, hr

    def forwardSentinel(self, s):
        s = self.lrelu(self.conv1(s))
        s = self.lrelu(self.conv2(s))
        s = self.lrelu(self.conv3(s))
        s = self.lrelu(self.conv4(s))

        ss = s.mean(2)
        s, _ = s.max(2)
        s = torch.cat([s, ss], dim=1)

        s = self.lrelu(self.conv5(s))
        s = self.lrelu(self.conv6(s))
        s = self.lrelu(self.conv7(s))
        return s

    def forwardClassifier(self, x, hr, s):
        xs = torch.cat([x, s], dim=1)
        xs = self.lrelu(self.merge1(xs))
        xs = torch.cat([x, s, xs], dim=1)
        xs = self.lrelu(self.merge2(xs))
        xs = torch.cat([x, s, xs], dim=1)
        xs = self.lrelu(self.merge3(xs))

        f = torch.nn.functional.interpolate(xs, size=(128, 128), mode="bilinear")
        f2 = torch.cat([f, hr], dim=1)
        f2 = self.lrelu(self.decod1(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod2(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod3(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod4(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        p = self.classif(f2)

        return p, xs

    def forward(self, x, s, mode=1):
        assert 1 <= mode <= 4

        if mode == 1:
            plow, x, hr = self.forwardRGB(x)
            s = self.forwardSentinel(s)
            p, _ = self.forwardClassifier(x, hr, s)
            p = torch.nn.functional.interpolate(p, size=(512, 512), mode="bilinear")
            return p + 0.1 * plow

        if mode == 2:
            plow, _, _ = self.forwardRGB(x)
            return plow

        if mode >= 3:
            if mode == 3:
                with torch.no_grad():
                    plow, x, hr = self.forwardRGB(x)
            else:
                plow, x, hr = self.forwardRGB(x)
            p, xs = self.forwardClassifier(x, hr, self.forwardSentinel(s))

            xs = self.compress(xs)
            xs = torch.nn.functional.interpolate(xs, size=(40, 40), mode="bilinear")
            xs = self.expand(xs)
            ps = torch.nn.functional.interpolate(p, size=(40, 40), mode="bilinear")
            ps = self.expand2(ps)
            xs = ps * xs

            xs = self.lrelu(self.generate1(xs))
            xs = self.lrelu(self.generate2(xs))
            xs = self.generate3(xs)
            xs = xs * 0.1 + 0.9 * torch.clamp(xs, -1, 1)
            assert xs.shape[1:] == (10, 40, 40)

            loss = ((xs - s.mean(2)) ** 2).flatten().mean()
            tmp = (xs.unsqueeze(2) - s) ** 2
            assert tmp.shape[1:] == (10, 32, 40, 40)
            losses = torch.zeros(tmp.shape[0]).cuda()
            for i in range(tmp.shape[0]):
                losses[i] = min([tmp[i, :, j, :, :].mean() for j in range(32)])
            loss = loss + losses.mean()

            p = torch.nn.functional.interpolate(p, size=(512, 512), mode="bilinear")
            return p + 0.1 * plow, loss


class MyNet3(torch.nn.Module):
    def __init__(self):
        super(MyNet3, self).__init__()
        tmp = torchvision.models.regnet_y_16gf(
            weights=torchvision.models.RegNet_Y_16GF_Weights.IMAGENET1K_V2
        )
        with torch.no_grad():
            old = tmp.stem[0].weight / 2
            tmp.stem[0] = torch.nn.Conv2d(6, 32, kernel_size=3, stride=2, padding=1)
            tmp.stem[0].weight = torch.nn.Parameter(torch.cat([old, old], dim=1))
        del tmp.trunk_output.block4
        del tmp.fc
        self.reg = tmp
        self.classiflow = torch.nn.Conv2d(1232, 13, kernel_size=1)

        ks = (2, 1, 1)
        self.conv1 = torch.nn.Conv3d(10, 32, kernel_size=ks, stride=ks, padding=0)
        self.conv2 = torch.nn.Conv3d(32, 64, kernel_size=ks, stride=ks, padding=0)
        self.conv3 = torch.nn.Conv3d(64, 92, kernel_size=(3, 3, 3))
        self.conv4 = torch.nn.Conv3d(92, 128, kernel_size=ks, stride=ks, padding=0)
        self.conv5 = torch.nn.Conv2d(256, 256, kernel_size=3)
        self.conv6 = torch.nn.Conv2d(256, 256, kernel_size=3)
        self.conv7 = torch.nn.Conv2d(256, 280, kernel_size=3)

        self.merge1 = torch.nn.Conv2d(1512, 512, kernel_size=1)
        self.merge2 = torch.nn.Conv2d(2024, 512, kernel_size=1)
        self.merge3 = torch.nn.Conv2d(2024, 112, kernel_size=1)

        self.decod1 = torch.nn.Conv2d(336, 112, kernel_size=1)
        self.decod2 = torch.nn.Conv2d(448, 112, kernel_size=1)
        self.decod3 = torch.nn.Conv2d(448, 112, kernel_size=3, padding=1)
        self.decod4 = torch.nn.Conv2d(448, 112, kernel_size=3, padding=1)
        self.classif = torch.nn.Conv2d(448, 13, kernel_size=1)

        self.lrelu = torch.nn.LeakyReLU(negative_slope=0.1, inplace=False)

    def forwardRGB(self, x):
        xm = torch.ones(x.shape[0], 1, 512, 512).cuda()
        xm = xm.to(dtype=x.dtype)
        x = ((x / 255) - 0.5) / 0.25
        x = x.to(dtype=xm.dtype)
        x = torch.cat([x, xm], dim=1)

        hr = self.reg.trunk_output.block1(self.reg.stem(x))  # 224
        x = self.reg.trunk_output.block3(self.reg.trunk_output.block2(hr))  # 1232
        plow = self.classiflow(x).float()
        plow = torch.nn.functional.interpolate(plow, size=(512, 512), mode="bilinear")

        return plow, x, hr

    def forwardSentinel(self, s):
        s = self.lrelu(self.conv1(s))
        s = self.lrelu(self.conv2(s))
        s = self.lrelu(self.conv3(s))
        s = self.lrelu(self.conv4(s))

        ss = s.mean(2)
        s, _ = s.max(2)
        s = torch.cat([s, ss], dim=1)

        s = self.lrelu(self.conv5(s))
        s = self.lrelu(self.conv6(s))
        s = self.lrelu(self.conv7(s))
        return s

    def forwardClassifier(self, x, hr, s):
        xs = torch.cat([x, s], dim=1)
        xs = self.lrelu(self.merge1(xs))
        xs = torch.cat([x, s, xs], dim=1)
        xs = self.lrelu(self.merge2(xs))
        xs = torch.cat([x, s, xs], dim=1)
        xs = self.lrelu(self.merge3(xs)).float()

        f = torch.nn.functional.interpolate(xs, size=(128, 128), mode="bilinear")
        f = f.to(dtype=hr.dtype)
        f2 = torch.cat([f, hr], dim=1)
        f2 = self.lrelu(self.decod1(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod2(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod3(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        f2 = self.lrelu(self.decod4(f2))
        f2 = torch.cat([f, f2, hr], dim=1)
        p = self.classif(f2)

        return p, xs

    def forward(self, x, s):
        plow, x, hr = self.forwardRGB(x)
        s = self.forwardSentinel(s)
        p, _ = self.forwardClassifier(x, hr, s)
        p = p.float()
        p = torch.nn.functional.interpolate(p, size=(512, 512), mode="bilinear")
        return p + 0.1 * plow


f = torch.load("build/model.pth")
g = MyNet3()

g.reg=f.reg
g.classiflow=f.classiflow
g.conv1=f.conv1
g.conv2=f.conv2
g.conv3=f.conv3
g.conv4=f.conv4
g.conv5=f.conv5
g.conv6=f.conv6
g.conv7=f.conv7
g.merge1=f.merge1
g.merge2=f.merge2
g.merge3=f.merge3
g.decod1=f.decod1
g.decod2=f.decod2
g.decod3=f.decod3
g.decod4=f.decod4
g.classif=f.classif

torch.save(g,"build/model_converted.pth")