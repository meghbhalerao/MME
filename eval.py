from __future__ import print_function


import argparse
import os
import torch
from model.resnet import resnet34, resnet50
from torch.autograd import Variable
from tqdm import tqdm
from model.basenet import AlexNetBase, VGGBase, Predictor, Predictor_deep, Predictor_attributes, Predictor_deep_attributes
from utils.return_dataset import return_dataset_test

# Training settings
parser = argparse.ArgumentParser(description='Visda Classification')
parser.add_argument('--T', type=float, default=0.05, metavar='T',
                    help='temperature (default: 0.05)')
parser.add_argument('--step', type=int, default=1000, metavar='step',
                    help='loading step')
parser.add_argument('--checkpath', type=str, default='./save_model_ssda',
                    help='dir to save checkpoint')
parser.add_argument('--method', type=str, default='MME',
                    choices=['S+T', 'ENT', 'MME'],
                    help='MME is proposed method, ENT is entropy minimization,'
                         'S+T is training only on labeled examples')
parser.add_argument('--output', type=str, default='./output.txt',
                    help='path to store result file')
parser.add_argument('--net', type=str, default='resnet34', metavar='B',
                    help='which network ')
parser.add_argument('--source', type=str, default='Art', metavar='B',
                    help='board dir')
parser.add_argument('--target', type=str, default='Clipart', metavar='B',
                    help='board dir')
parser.add_argument('--dataset', type=str, default ='multi',
                    choices=['multi','office_home'], help='the name of dataset, multi is large scale dataset')
parser.add_argument('--num', type=int, default=3,
                    help='number of labeled examples in the target')
parser.add_argument('--dim', type=int, default=300,
                        help='dimensionality of the feature vector - make sure this in sync with the dim of the semantic attribute vector') 

args = parser.parse_args()
print('dataset %s source %s target %s network %s' %
      (args.dataset, args.source, args.target, args.net))
target_loader_unl, class_list = return_dataset_test(args)
use_gpu = torch.cuda.is_available()

if args.net == 'resnet34':
    G = resnet34()
    inc = 512
elif args.net == 'resnet50':
    G = resnet50()
    inc = 2048
elif args.net == "alexnet":
    G = AlexNetBase()
    inc = 4096
elif args.net == "vgg":
    G = VGGBase()
    inc = 4096
else:
    raise ValueError('Model cannot be recognized.')


if "resnet" in args.net:
    F1 = Predictor_deep_attributes(num_class=len(class_list),
                        inc=inc, feat_dim = args.dim)
else:
    F1 = Predictor_attributes(num_class=len(class_list), inc=inc, temp=args.T, feat_dim = args.dim)



# Loading the model weights from the checkpoint
#filename = '%s/%s_%s_%s_%s.ckpt.best.pth.tar' % (args.checkpath, args.net, args.method, args.source, args.target)
filename = "save_model_ssda/alexnet_MME_real_painting_1_exp1.ckpt.best.pth.tar"
main_dict = torch.load(filename)
args.step = main_dict['step']
print("Inferencing is being done with model at step: ", args.step)
print("best accuracy, ", main_dict['best_acc_test'])
print(main_dict)
G.cuda()
F1.cuda()
G.load_state_dict(main_dict['G_state_dict'])
F1.load_state_dict(main_dict['F1_state_dict'])

im_data_t = torch.FloatTensor(1)
gt_labels_t = torch.LongTensor(1)

im_data_t = im_data_t.cuda()
gt_labels_t = gt_labels_t.cuda()

im_data_t = Variable(im_data_t)
gt_labels_t = Variable(gt_labels_t)

if os.path.exists(args.checkpath) == False:
    os.mkdir(args.checkpath)

def eval(loader, output_file="output.txt"):
    G.eval()
    F1.eval()
    size = 0
    with open(output_file, "w") as f:
        with torch.no_grad():
            for batch_idx, data_t in tqdm(enumerate(loader)):
                im_data_t.data.resize_(data_t[0].size()).copy_(data_t[0])
                gt_labels_t.data.resize_(data_t[1].size()).copy_(data_t[1])
                paths = data_t[2]
                feat = G(im_data_t)
                output1 = F1(feat)
                size += im_data_t.size(0)
                pred1 = output1.data.max(1)[1]
                for i, path in enumerate(paths):
                    f.write("%s %d\n" % (path, pred1[i]))


eval(target_loader_unl, output_file="%s_%s_%s.txt" % (args.method, args.net,
                                                      args.step))