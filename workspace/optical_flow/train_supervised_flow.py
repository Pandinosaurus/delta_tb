import numpy as np
import os
from glob import glob
from tqdm import tqdm

import torch
from torchvision import transforms

import sys
sys.path.insert(0, "../..")

from deltatb import networks
from deltatb.losses.multiscale import MultiscaleLoss
from deltatb.metrics.optical_flow import EPE
from deltatb.dataset.datasets import SegmentationDataset
from deltatb.dataset.transforms import NormalizeDynamic
#from deltatb.dataset.transforms import RandomAsymBlur
from deltatb.dataset.transforms import RandomBrightnessChange, RandomContrastChange
#from deltatb.dataset.transforms import PILRandomBrightnessAndContrastChange
from deltatb.dataset import co_transforms
from deltatb.dataset import flow_co_transforms

from deltatb.tools.visdom_display import VisuVisdom
from backend import flow_to_color_tensor, upsample_output_and_evaluate
from backend import image_loader_gray, flow_loader
from backend import CenterZeroPadMultiple, MultiFactorMultiStepLR

import argparse

#dev_and_debug: 
#ipython -i -- train_supervised_flow.py + arguments
# --savedir dev_and_debug
# --expname optim_state
# --chairs --test-sintel
# --do-not-save-visu
# --nb-iter-per-epoch 16
# --chairs-nb-epochs 15
# --test-interval 1
# --visu-visdom
# --step-by-step
# --scheduler-step-indices 100 150 200 250 300 350 --scheduler-factors 0.5 0.5 0.5 4.0 0.5 0.5
# ATTENTION scheduler_step_indices = [5, 10] #[100, 150, 200]

parser = argparse.ArgumentParser()
parser.add_argument("--bs", type=int, default=8) #taille du batch
parser.add_argument("--nw", type=int, default=2) #nombre de coeurs cpu à utiliser pour chargement des données
parser.add_argument("--savedir", type=str, default="dev_and_debug")
parser.add_argument("--expname", type=str, default="optim_state")
parser.add_argument("--arch", type=str, default='PWCDCNet_siamese')
parser.add_argument('--pretrained', dest='pretrained', default=None, metavar='PATH', help='path to pre-trained model')
parser.add_argument("--test-only", action="store_true")
parser.add_argument("--step-by-step", action="store_true")
parser.add_argument("--chairs", action="store_true")
parser.add_argument("--things", action="store_true")
parser.add_argument("--things-clean", action="store_true")
parser.add_argument("--test-sintel", action="store_true")
parser.add_argument("--ignore-nan", action="store_true")
parser.add_argument("--chairs-path", type=str, default='/data/FlyingChairs_splitted')
parser.add_argument("--things-path", type=str, default='/scratch/FLOW_DATASETS/flying_things_3D')
parser.add_argument("--sintel-path", type=str, default='/data/eval_flow/sintel')

parser.add_argument("--nb-iter-per-epoch", type=int, default=1000)
parser.add_argument("--chairs-lr", type=float, default=0.0001) # learning rate
parser.add_argument("--chairs-nb-epochs", type=int, default=300) #nombre d'epochs
# parser.add_argument(chairs scheduler step indices) et valeurs du lr
parser.add_argument("--things-lr", type=float, default=0.00001) # learning rate
parser.add_argument("--things-nb-epochs", type=int, default=300) #nombre d'epochs

parser.add_argument('--device', type=int, default=0)
parser.add_argument("--no-cuda", action="store_true")

#parser.add_argument("--saveimages", action="store_true")
parser.add_argument("--test-interval", type=int, default=5)
parser.add_argument("--display-interval", type=int, default=100)
parser.add_argument("--visu-visdom", action="store_true")
parser.add_argument("--do-not-save-visu", action="store_true")
parser.add_argument("--visdom-port", type=int, default=8094)
parser.add_argument('--chairs-scheduler-step-indices', nargs='*', default=[-1], type=int,
                    help='List of epoch indices for learning rate decay. Must be increasing. No decay if -1')
parser.add_argument('--chairs-scheduler-factors', nargs='*', default=[0.1], type=float,
                    help='multiplicative factor applied on lr each step-size')
parser.add_argument('--things-scheduler-step-indices', nargs='*', default=[-1], type=int,
                    help='List of epoch indices for learning rate decay. Must be increasing. No decay if -1')
parser.add_argument('--things-scheduler-factors', nargs='*', default=[0.1], type=float,
                    help='multiplicative factor applied on lr each step-size')
#parser.add_argument('--scheduler-factor', default=0.1, type=float,
#                    help='multiplicative factor applied on lr each step-size')
args = parser.parse_args()


#########
#Parameters
#########
exp_name = args.expname
save_dir = os.path.join(args.savedir, exp_name) # path the directory where to save the model and results
num_workers = args.nw
batch_size = args.bs
chairs_lr = args.chairs_lr
things_lr = args.things_lr
chairs_nbr_epochs = args.chairs_nb_epochs # training epoch
things_nbr_epochs = args.things_nb_epochs # training epoch
nbr_iter_per_epochs = args.nb_iter_per_epoch # number of iterations for one epoch
chairs_imsize = 320, 448 # input image size
things_imsize = 448, 768
#scheduler_step_indices = [100, 150, 200]
#scheduler_factor = 0.5
#scheduler_step_indices = [100, 150, 200, 250, 300, 350]
#scheduler_factors =      [0.5, 0.5, 0.5, 4.0, 0.5, 0.5]
chairs_scheduler_step_indices = args.chairs_scheduler_step_indices
chairs_scheduler_factors = args.chairs_scheduler_factors
things_scheduler_step_indices = args.things_scheduler_step_indices
things_scheduler_factors = args.things_scheduler_factors
div_flow = 20
weight_decay = 0.0004
in_channels = 2
out_channels = 2
use_cuda = (not args.no_cuda) and torch.cuda.is_available() # use cuda GPU

##########

args_file = os.path.join(save_dir, 'args.txt')
if not os.path.exists(save_dir):
    os.makedirs(save_dir)
with open(args_file, 'w') as f:
    for k, v in sorted(vars(args).items()):
        f.write('{}: {}\n'.format(k, v))

#########

if use_cuda:
    torch.backends.cudnn.benchmark = True # accelerate convolution computation on GPU
    torch.cuda.set_device(args.device)

########
#Normalization, for every data
########
''' ATTENTION les transformation de brightness et contrast ne sont pas encore bonnes... Refaire avec PIL ?
input_transforms = transforms.Compose([RandomBrightnessChange(0.2), 
                                        RandomContrastChange(-0.8, 0.4),
                                        NormalizeDynamic(3),
                                        transforms.ToTensor()])
'''
input_transforms = transforms.Compose([NormalizeDynamic(3),
                                        transforms.ToTensor()])
#'''
#########
#Model, loss, optimizer
#########
print("Creating the model...", end="", flush=True)
net = networks.__dict__[args.arch](input_channels=in_channels, div_flow=div_flow)
if args.pretrained:
    pretrained_data = torch.load(args.pretrained,
                                map_location=lambda storage,
                                loc: storage.cuda(args.device))
    if 'model_state_dict' in pretrained_data.keys():
        net.load_state_dict(pretrained_data['model_state_dict'])
    elif 'state_dict' in pretrained_data.keys():
        net.load_state_dict(pretrained_data['state_dict'])
    else:
        net.load_state_dict(pretrained_data)
#net = networks.FlowNetS(in_channels, out_channels, div_flow=div_flow)
if use_cuda:
    net.cuda()
print("done")

loss_fct = MultiscaleLoss(EPE(mean=False, ignore_nan=args.ignore_nan))
err_fct = EPE(mean=True)

print("Creating optimizer...", end="", flush=True)
#parameters = filter(lambda p: p.requires_grad, net.parameters())
chairs_optimizer = torch.optim.Adam(net.parameters(), chairs_lr, weight_decay=weight_decay)
things_optimizer = torch.optim.Adam(net.parameters(), things_lr, weight_decay=weight_decay)
#chairs_scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer,
#                                    scheduler_step_indices, scheduler_factor)
chairs_scheduler = MultiFactorMultiStepLR(chairs_optimizer,
                                    chairs_scheduler_step_indices, chairs_scheduler_factors)
things_scheduler = MultiFactorMultiStepLR(things_optimizer,
                                    things_scheduler_step_indices, things_scheduler_factors)
print("done")

#########
#Visu
#########
if args.visu_visdom:
    visu = VisuVisdom(exp_name, port=args.visdom_port)
    display_max_flo = 40

#########
#Training
#########
def train(epoch, nbr_batches, optimizer, train_loader):
    nbr_batches = len(train_loader) if nbr_batches <= 0 else min(len(train_loader), nbr_batches)
    net.train()
    error = 0
    i = 0
    t = tqdm(train_loader, total=nbr_batches, ncols=100, desc="Epoch "+str(epoch))
    for img_pair_th, target_th in t:
        if use_cuda:
            img_pair_th = [image.cuda() for image in img_pair_th]
            target_th = target_th.cuda()
            #img_pair_th = [image.cuda(async=True) for image in img_pair_th] #et pin_memory ?
            #target_th = target_th.cuda(async=True)
        output = net(img_pair_th)
        error_ = loss_fct(output, target_th)
        optimizer.zero_grad()
        error_.backward()
        optimizer.step()

        i += 1
        error += error_.data
        loss = error / i

        # display TQDM
        t.set_postfix(Loss="%.3e"%float(loss))

        #display visdom
        if i % args.display_interval == 0 and args.visu_visdom:
            visu.imshow(img_pair_th[0], 'Images (train)', unnormalize=True)
            color_target_flow = flow_to_color_tensor(target_th, display_max_flo / div_flow)
            visu.imshow(color_target_flow, 'Flots VT (train)')
            if False:
                visu.imshow(mask_vt, 'Mask VT (train)')
            for k, out in enumerate(output):
                color_output_flow = flow_to_color_tensor(out.data, display_max_flo / div_flow)
                visu.imshow(color_output_flow, 'Flots (train)[{}]'.format(k))

        #Liberation memoire:
        del output

        if i >= nbr_batches:
                break

    t.close()
    return loss.item()

def test(epoch, filelist_test, title='test'):
    net.eval()

    with torch.no_grad():
        test_input_transforms = transforms.Compose([NormalizeDynamic(3),
                                                    CenterZeroPadMultiple(64),
                                                    transforms.ToTensor()])
        test_target_transforms = transforms.Compose([CenterZeroPadMultiple(64),
                                                        transforms.ToTensor()])
        test_dataset = SegmentationDataset(filelist=filelist_test,
                                    image_loader=image_loader_gray,
                                    target_loader=flow_loader,
                                    training=False, co_transforms=None,
                                    input_transforms=test_input_transforms,
                                    target_transforms=test_target_transforms)

        test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=batch_size,
                                                    shuffle=False, num_workers=num_workers)

        t = tqdm(test_loader, ncols=100, desc="Image")
        err_moy = 0

        for img_pair_th, target_th in t:
            if use_cuda:
                img_pair_th = [image.cuda() for image in img_pair_th]
                target_th = target_th.cuda()
                #img_pair_th = [image.cuda(async=True) for image in img_pair_th]
                #target_th = target_th.cuda(async=True) # et pin_memory ds dataloader?

            # forward backward
            output = net(img_pair_th)
            err = upsample_output_and_evaluate(err_fct, output, target_th)
            err_moy += err.data

            t.set_postfix(EPE="%.3e"%float(err))

            #display visdom
            if args.visu_visdom:
                visu.imshow(img_pair_th[0], 'Images ({})'.format(title), unnormalize=True)
                color_target_flow = flow_to_color_tensor(target_th, display_max_flo)
                visu.imshow(color_target_flow, 'Flots VT ({})'.format(title))
                for k, out in enumerate(output):
                    color_output_flow = flow_to_color_tensor(out.data, display_max_flo)
                    visu.imshow(color_output_flow, 'Flots ({})[{}]'.format(title, k))

        t.close()
        return err_moy.item() / len(test_loader)

def iterate_all_epochs(nbr_epochs, optimizer, scheduler, train_loader, filelist_test, filelist_sintel=None):
    for epoch in range(nbr_epochs):
        scheduler.step()
        train_loss = train(epoch, nbr_iter_per_epochs, optimizer, train_loader)

        # save the model (checkpoint)
        torch.save(net.state_dict(), os.path.join(save_dir, "state_dict_checkpoint.pth"))
        torch.save(optimizer.state_dict(), os.path.join(save_dir, "optim_state_dict_checkpoint.pth"))

        #display visdom
        if args.visu_visdom:
            visu.plot('Training Loss', epoch+1, train_loss)

        # test
        if ((epoch+1)%args.test_interval==0) or (epoch == nbr_epochs-1):
            print("Testing {}".format(exp_name), flush=True)
            test_err = test(epoch, filelist_test)
            if filelist_sintel:
                print("Testing {} on sintel".format(exp_name), flush=True)
                sintel_err = test(epoch, filelist_sintel, 'sintel')

            #display visdom
            if args.visu_visdom:
                visu.plot('Validation Error', epoch+1, test_err)
                if filelist_sintel:
                    visu.plot('Sintel Error', epoch+1, sintel_err)

            # write the logs
            f.write(str(epoch)+" ")
            f.write("%.4e "%train_loss)
            f.write("%.4f "%test_err)
            if filelist_sintel:
                f.write("%.4f "%sintel_err)
            f.write("\n")
            f.flush()

# generate filename for saving model
print("Models and logs will be saved to: {}".format(save_dir), flush=True)
os.makedirs(save_dir, exist_ok=True)

f = open(os.path.join(save_dir, "logs.txt"), "w")
if args.test_sintel:
    f.write("Epoch  train_loss  test_epe[px]  sintel_epe[px]\n")
else:
    f.write("Epoch  train_loss  test_epe[px]\n")
f.flush()

#########
#Prepare MiniSintel for testing
#########
def get_filelist_minisintel(path, time_step=10, clean=False):
    """
    1 paire d'images par séquence.
    time_step commence à 1 (choix de l'instant pour chaque séquence)
    """
    dir_list_flow = sorted(glob(os.path.join(path, 'flow/*')))
    dir_list_images = sorted(glob(os.path.join(path, 'clean/*' if clean else 'final/*')))

    list_batches = []
    for k in range(len(dir_list_flow)):
        list_batches.append((
                            [ os.path.join(dir_list_images[k], 'frame_{:04d}.png'.format(time_step)), 
                            os.path.join(dir_list_images[k], 'frame_{:04d}.png'.format(time_step+1)) ], 
                            os.path.join(dir_list_flow[k], 'frame_{:04d}.flo'.format(time_step)) 
                                ))
    return list_batches

if args.test_sintel:
    filelist_sintel = get_filelist_minisintel(args.sintel_path, clean=False)
else:
    filelist_sintel = None

#########
#PreTrain on Chairs
#########
def get_filelist_flyingchairs(path):
    list_imgs1 = sorted(glob(os.path.join(path, 'IMAGES/*img1.ppm')))
    list_imgs2 = sorted(glob(os.path.join(path, 'IMAGES/*img2.ppm')))
    list_flows = sorted(glob(os.path.join(path, 'FLOW/*flow.flo')))
    list_batches = []
    for k in range(len(list_imgs1)):
        list_batches.append(([list_imgs1[k], list_imgs2[k]], list_flows[k]))
    return list_batches

if args.chairs:
    path_test = os.path.join(args.chairs_path, 'TEST')
    filelist_test = get_filelist_flyingchairs(path_test)
    if args.test_only:
        print("Testing {}".format(exp_name), flush=True)
        test_err = test(0, filelist_test)
        if args.test_sintel:
            sintel_err = test(0, filelist_sintel)

        #display visdom
        if args.visu_visdom:
            visu.plot('Validation Error', 1, test_err)
            if args.test_sintel:
                visu.plot('Sintel Error', 1, sintel_err)

        # write the logs
        f.write(str(0)+" ")
        f.write("  -  ") #train_loss does not exist
        f.write("%.4f "%test_err)
        if args.test_sintel:
            f.write("%.4f "%sintel_err)
        f.write("\n")
        f.flush()
    else:
        print("Creating chairs training loader...", end="", flush=True)

        train_co_transforms = co_transforms.Compose([
                                    flow_co_transforms.RandomTranslate(10),
                                    flow_co_transforms.RandomRotate(10,5),
                                    co_transforms.RandomCrop(chairs_imsize),
                                    flow_co_transforms.RandomVerticalFlip(),
                                    flow_co_transforms.RandomHorizontalFlip(),
                                        ])

        train_target_transforms = transforms.Compose([
                                        lambda target: target / div_flow,
                                        transforms.ToTensor()])

        path_train = os.path.join(args.chairs_path, 'TRAIN')
        filelist_train = get_filelist_flyingchairs(path_train)        

        train_dataset = SegmentationDataset(filelist=filelist_train,
                            image_loader=image_loader_gray,
                            target_loader=flow_loader,
                            training=True, co_transforms=train_co_transforms,
                            input_transforms=input_transforms,
                            target_transforms=train_target_transforms)

        train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size,
                                                    shuffle=True, num_workers=num_workers)
        print("Done")

        if not args.step_by_step:
            #iterate_all_epochs(chairs_nbr_epochs, chairs_scheduler, train_loader, filelist_test)
            iterate_all_epochs(chairs_nbr_epochs, chairs_optimizer, chairs_scheduler, train_loader, filelist_test, filelist_sintel)
            print('Pretraining on chairs done')
            # save the model pretrained on chairs
            torch.save(net.state_dict(), os.path.join(save_dir, "state_dict_chairs.pth"))
            print('Model pretrained on chairs saved')

#########
#Train on Things
#########
def get_filelist_things(path, train=True, clean=False):
    """
    1 paire d'images par séquence.
    time_step commence à 1 (choix de l'instant pour chaque séquence)
    """
    if clean:
        dstype = 'frames_cleanpass'
    else:
        dstype = 'frames_finalpass'
    
    image_dirs = sorted(glob(os.path.join(path, dstype, '{}/*/*'.format('TRAIN' if train else 'TEST'))))
    image_dirs = sorted([os.path.join(f, 'left') for f in image_dirs] + [os.path.join(f, 'right') for f in image_dirs])

    flow_dirs = sorted(glob(os.path.join(path, 'optical_flow/{}/*/*'.format('TRAIN' if train else 'TEST'))))
    flow_dirs = sorted([os.path.join(f, 'into_future/left') for f in flow_dirs] + [os.path.join(f, 'into_future/right') for f in flow_dirs])

    assert (len(image_dirs) == len(flow_dirs))

    list_samples = []

    for idir, fdir in zip(image_dirs, flow_dirs):
        images = sorted( glob(os.path.join(idir, '*.png')) )
        flows = sorted( glob(os.path.join(fdir, '*.pfm')) )
        for i in range(len(flows)-1):
            list_samples.append((
                                [ images[i], images[i+1] ],
                                flows[i]
                                    ))
    return list_samples


if args.things:
    if args.test_only:
        print("Testing {}".format(exp_name), flush=True)
        if args.test_sintel:
            sintel_err = test(0, filelist_sintel)

        #display visdom
        if args.visu_visdom:
            if args.test_sintel:
                visu.plot('Sintel Error', 1, sintel_err)

        # write the logs
        f.write(str(0)+" ")
        f.write("  -  ") #train_loss does not exist
        if args.test_sintel:
            f.write("%.4f "%sintel_err)
        f.write("\n")
        f.flush()
    else:
        print("Creating things training loader...", end="", flush=True)

        train_co_transforms = co_transforms.Compose([
                                    flow_co_transforms.RandomTranslate(10),
                                    flow_co_transforms.RandomRotate(10,5),
                                    co_transforms.RandomCrop(things_imsize),
                                    flow_co_transforms.RandomVerticalFlip(),
                                    flow_co_transforms.RandomHorizontalFlip(),
                                        ])

        train_target_transforms = transforms.Compose([
                                        lambda target: target / div_flow,
                                        transforms.ToTensor()])

        path_train = args.things_path
        filelist_train = get_filelist_things(path_train, clean=args.things_clean)        

        train_dataset = SegmentationDataset(filelist=filelist_train,
                            image_loader=image_loader_gray,
                            target_loader=flow_loader,
                            training=True, co_transforms=train_co_transforms,
                            input_transforms=input_transforms,
                            target_transforms=train_target_transforms)

        train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size,
                                                    shuffle=True, num_workers=num_workers)
        print("Done")

        if not args.step_by_step:
            #iterate_all_epochs(things_nbr_epochs, things_scheduler, train_loader, filelist_test, filelist_sintel)
            iterate_all_epochs(things_nbr_epochs, things_optimizer, things_scheduler, train_loader, filelist_sintel)
            print('Training on things done')
            # save the model pretrained on things
            torch.save(net.state_dict(), os.path.join(save_dir, "state_dict_things.pth"))
            print('Model trained on things saved')

if args.visu_visdom and not args.do_not_save_visu:
    visu.save()
f.close()
