from __future__ import print_function
import argparse
import os
import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
from model.resnet import resnet34
from model.basenet import AlexNetBase, VGGBase, Predictor, Predictor_deep, Predictor_deep_attributes, Predictor_attributes
from utils.utils import weights_init, save_mymodel, save_checkpoint
from utils.lr_schedule import inv_lr_scheduler
from utils.return_dataset import return_dataset
from utils.loss import entropy, adentropy, FocalLoss, CBFocalLoss
import pandas as pd

def main():
    # Training settings
    parser = argparse.ArgumentParser(description='SSDA Classification')
    parser.add_argument('--steps', type=int, default=50000, metavar='N',
                        help='maximum number of iterations '
                            'to train (default: 50000)')
    parser.add_argument('--method', type=str, default='MME',
                        choices=['S+T', 'ENT', 'MME'],
                        help='MME is proposed method, ENT is entropy minimization,'
                            ' S+T is training only on labeled examples')
    parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                        help='learning rate (default: 0.001)')
    parser.add_argument('--multi', type=float, default=0.1, metavar='MLT',
                        help='learning rate multiplication')
    parser.add_argument('--T', type=float, default=0.05, metavar='T',
                        help='temperature (default: 0.05)')
    parser.add_argument('--lamda', type=float, default=0.1, metavar='LAM',
                        help='value of lamda')
    parser.add_argument('--save_check', action='store_true', default=False,
                        help='save checkpoint or not')
    parser.add_argument('--checkpath', type=str, default='./save_model_ssda',
                        help='dir to save checkpoint')
    parser.add_argument('--seed', type=int, default=1, metavar='S',
                        help='random seed (default: 1)')
    parser.add_argument('--log-interval', type=int, default=100, metavar='N',
                        help='how many batches to wait before logging '
                            'training status')
    parser.add_argument('--save_interval', type=int, default=500, metavar='N',
                        help='how many batches to wait before saving a model')
    parser.add_argument('--net', type=str, default='alexnet',
                        help='which network to use')
    parser.add_argument('--source', type=str, default='real',
                        help='source domain')
    parser.add_argument('--target', type=str, default='sketch',
                        help='target domain')
    parser.add_argument('--dataset', type=str, default='multi',
                        choices=['multi', 'office', 'office_home'],
                        help='the name of dataset')
    parser.add_argument('--num', type=int, default=3,
                        help='number of labeled examples in the target')
    parser.add_argument('--patience', type=int, default=5, metavar='S',
                        help='early stopping to wait for improvment '
                            'before terminating. (default: 5 (5000 iterations))')
    parser.add_argument('--early', action='store_false', default=True,
                        help='early stopping on validation or not')
    parser.add_argument('--loss',type=str, default='CE',choices=['CE', 'FL','CBFL'],
                        help='classifier loss function')
    parser.add_argument('--attribute', type = str, default = None,
                        choices = ['word2vec','glove.6B.100d.txt','glove.6B.300d.txt','glove_anurag','fasttext_anurag','glove.840B.300d.txt','glove.twitter.27B.200d.txt', 'glove.twitter.27B.50d.txt' ,'glove.42B.300d.txt','glove.6B.200d.txt','glove.6B.50d.txt','glove.twitter.27B.100d.txt','glove.twitter.27B.25d.txt'],
                        help='semantic attribute feature vector to be used')
    parser.add_argument('--dim', type=int, default=300,
                        help='dimensionality of the feature vector - make sure this in sync with the dim of the semantic attribute vector')    
    parser.add_argument('--deep', type=int, default=0,
                        help='type of classification predictor - 0 for shallow, 1 for deep')
    parser.add_argument('--mode', type=str, default='train', choices=['train', 'infer'], help = 'mode of script train or infer')
 

    args = parser.parse_args()
    print('Dataset %s Source %s Target %s Labeled num perclass %s Network %s' %
        (args.dataset, args.source, args.target, args.num, args.net))
    source_loader, target_loader, target_loader_unl, target_loader_val, \
        target_loader_test, class_num_list, class_list = return_dataset(args) # class num list is returned for CBFL 
    use_gpu = torch.cuda.is_available()
    record_dir = 'record/%s/%s' % (args.dataset, args.method)
    if not os.path.exists(record_dir):
        os.makedirs(record_dir)
    record_file = os.path.join(record_dir,
                            '%s_net_%s_%s_to_%s_num_%s' %
                            (args.method, args.net, args.source,
                                args.target, args.num))
    if use_gpu:
        device = 'cuda'
    else:
        device = 'cpu'
    
    print("Device: %s  Loss: %s  Attributes: %s"%(device,args.loss,args.attribute))
    
    if use_gpu:
        torch.cuda.manual_seed(args.seed)
    else:
        torch.manual_seed(args.seed)

    if args.net == 'resnet34':
        G = resnet34()
        inc = 512
    elif args.net == "alexnet":
        G = AlexNetBase()
        inc = 4096
    elif args.net == "vgg":
        G = VGGBase()
        inc = 4096
    else:
        raise ValueError('Model cannot be recognized.')
    params = []
    for key, value in dict(G.named_parameters()).items():
        if value.requires_grad:
            if 'classifier' not in key:
                params += [{'params': [value], 'lr': 0.1,
                            'weight_decay': 0.0005}]
            else:
                params += [{'params': [value], 'lr': 1,
                            'weight_decay': 0.0005}]

    # Setting the predictor layer
    if args.attribute is not None:
        if args.deep:
            F1 = Predictor_deep_attributes(num_class=len(class_list),inc=inc,feat_dim = args.dim)
            print("Using: Predictor_deep_attributes")
        else:
            F1 = Predictor_attributes(num_class=len(class_list),inc=inc,feat_dim = args.dim)
            print("Using: Predictor_attributes")
    else:
        if args.deep:
            F1 = Predictor_deep(num_class=len(class_list),inc=inc)
            print("Using: Predictor_deep")
        else:
            F1 = Predictor(num_class=len(class_list), inc=inc, temp=args.T)
            print("Using: Predictor")


    # Initializing the weights of the prediction layer
    weights_init(F1)
	# Setting the prediction layer weights as the semantic attributes
    if args.attribute is not None:
        att = np.load('attributes/%s_%s.npy'%(args.dataset,args.attribute))    
        if use_gpu:
            att = nn.Parameter(torch.cuda.FloatTensor(att))
        else:
            att = nn.Parameter(torch.FloatTensor(att,device = "cpu"))
        if args.deep:
            F1.fc3.weight = att
        else:
            F1.fc2.weight = att
        print("attribute shape is: ", att.shape)

    lr = args.lr

     
    # loading the model checkpoint - and printing some parameters relating to the checkpoints
    main_dict = torch.load(args.checkpath + "/" + args.net + "_" + args.method + "_" + args.source + "_" + args.target + ".ckpt.best.pth.tar")	
    G.load_state_dict(main_dict['G_state_dict'])
    F1.load_state_dict(main_dict['F1_state_dict'])
    print("Loaded pretrained model weights")  
    print("Loaded weights from step: ", main_dict['step'])
    print("Current best test acc is: ",main_dict['best_acc_test'])
    G.to(device)
    F1.to(device)
    # Loading the txt file having the weights and paths of the image file as a data frame
    df = pd.read_csv(args.method + '_' + main_dict['arch'] + '_' + str(main_dict['step']) + '.txt', sep=" ", header=None)
    df = df[[3,0]]
    df  = df.rename(columns={3: "img", 0: "weight"})
    im_data_s = torch.FloatTensor(1)
    im_data_t = torch.FloatTensor(1)
    im_data_tu = torch.FloatTensor(1)
    gt_labels_t = torch.LongTensor(1)
    gt_labels_s = torch.LongTensor(1)
    sample_labels_t = torch.LongTensor(1)
    sample_labels_s = torch.LongTensor(1)

    im_data_s = im_data_s.to(device)
    im_data_t = im_data_t.to(device)
    im_data_tu = im_data_tu.to(device)
    gt_labels_s = gt_labels_s.to(device)
    gt_labels_t = gt_labels_t.to(device)
    sample_labels_t = sample_labels_t.to(device)
    sample_labels_s = sample_labels_s.to(device)


    im_data_s = Variable(im_data_s)
    im_data_t = Variable(im_data_t)
    im_data_tu = Variable(im_data_tu)
    gt_labels_s = Variable(gt_labels_s)
    gt_labels_t = Variable(gt_labels_t)
    sample_labels_t = Variable(sample_labels_t)
    sample_labels_s = Variable(sample_labels_s)
 

    if os.path.exists(args.checkpath) == False:
        os.mkdir(args.checkpath)


    def train():
        G.train()
        F1.train()
        optimizer_g = optim.SGD(params, momentum=0.9,
                                weight_decay=0.0005, nesterov=True)
        optimizer_f = optim.SGD(list(F1.parameters()), lr=1.0, momentum=0.9,
                                weight_decay=0.0005, nesterov=True)

        # Loading the states of the two optmizers
        optimizer_g.load_state_dict(main_dict['optimizer_g'])
        optimizer_f.load_state_dict(main_dict['optimizer_f'])
        print("Loaded optimizer states")

        def zero_grad_all():
            optimizer_g.zero_grad()
            optimizer_f.zero_grad()
        param_lr_g = []
        for param_group in optimizer_g.param_groups:
            param_lr_g.append(param_group["lr"])
        param_lr_f = []
        for param_group in optimizer_f.param_groups:
            param_lr_f.append(param_group["lr"])


       
        # Setting the loss function to be used for the classification loss
        if args.loss == 'CE':
            criterion = nn.CrossEntropyLoss().to(device)
        if args.loss == 'FL':
            criterion = FocalLoss(alpha = 1, gamma = 1).to(device)
        if args.loss == 'CBFL':
            # Calculating the list having the number of examples per class which is going to be used in the CB focal loss
            beta = 0.99
            effective_num = 1.0 - np.power(beta, class_num_list)
            per_cls_weights = (1.0 - beta) / np.array(effective_num)
            per_cls_weights = per_cls_weights / np.sum(per_cls_weights) * len(class_num_list)
            per_cls_weights = torch.FloatTensor(per_cls_weights).to(device)
            criterion = CBFocalLoss(weight=per_cls_weights, gamma=0.5).to(device)
     
        all_step = args.steps
        data_iter_s = iter(source_loader)
        data_iter_t = iter(target_loader)
        data_iter_t_unl = iter(target_loader_unl)
        len_train_source = len(source_loader)
        len_train_target = len(target_loader)
        len_train_target_semi = len(target_loader_unl)
        best_acc = 0
        counter = 0
        for step in range(all_step):
            optimizer_g = inv_lr_scheduler(param_lr_g, optimizer_g, step,
                                        init_lr=args.lr)
            optimizer_f = inv_lr_scheduler(param_lr_f, optimizer_f, step,
                                        init_lr=args.lr)
            lr = optimizer_f.param_groups[0]['lr']
            # condition for restarting the iteration for each of the data loaders 
            if step % len_train_target == 0:
                data_iter_t = iter(target_loader)
            if step % len_train_target_semi == 0:
                data_iter_t_unl = iter(target_loader_unl)
            if step % len_train_source == 0:
                data_iter_s = iter(source_loader)
            data_t = next(data_iter_t)
            data_t_unl = next(data_iter_t_unl)
            data_s = next(data_iter_s)
            with torch.no_grad():
                im_data_s.resize_(data_s[0].size()).copy_(data_s[0])
                gt_labels_s.resize_(data_s[1].size()).copy_(data_s[1])
                im_data_t.resize_(data_t[0].size()).copy_(data_t[0])
                gt_labels_t.resize_(data_t[1].size()).copy_(data_t[1])
                im_data_tu.resize_(data_t_unl[0].size()).copy_(data_t_unl[0])
            
     
            zero_grad_all()
            data = torch.cat((im_data_s, im_data_t), 0)
            target = torch.cat((gt_labels_s, gt_labels_t), 0)
            output = G(data)
            out1 = F1(output)
            loss = criterion(out1, target)
            loss.backward(retain_graph=True)
            optimizer_g.step()
            optimizer_f.step()
            zero_grad_all()
            # list of the weights and image paths in this batch
            img_paths = list(data_t_unl[2])
            df1  = df.loc[df['img'].isin(img_paths)] 
            df1 = df1['weight']
            weight_list = list(df1)

            if not args.method == 'S+T':
                output = G(im_data_tu)
                if args.method == 'ENT':
                    loss_t = entropy(F1, output, args.lamda)
                    loss_t.backward()
                    optimizer_f.step()
                    optimizer_g.step()
                elif args.method == 'MME':
                    loss_t = adentropy(F1, output,args.lamda, weight_list)
                    loss_t.backward()
                    optimizer_f.step()
                    optimizer_g.step()
                else:
                    raise ValueError('Method cannot be recognized.')
                log_train = 'S {} T {} Train Ep: {} lr{} \t ' \
                            'Loss Classification: {:.6f} Loss T {:.6f} ' \
                            'Method {}\n'.format(args.source, args.target,
                                                step, lr, loss.data,
                                                -loss_t.data, args.method)
            else:
                log_train = 'S {} T {} Train Ep: {} lr{} \t ' \
                            'Loss Classification: {:.6f} Method {}\n'.\
                    format(args.source, args.target,
                        step, lr, loss.data,
                        args.method)
            G.zero_grad()
            F1.zero_grad()
            zero_grad_all()
            if step % args.log_interval == 0:
                print(log_train)
            if step % args.save_interval == 0 and step > 0:
                loss_val, acc_val = test(target_loader_val)
                loss_test, acc_test = test(target_loader_test)
                G.train()
                F1.train()
                if acc_test >= best_acc:
                    best_acc = acc_test
                    best_acc_test = acc_test
                    counter = 0
                else:
                    counter += 1
                if args.early:
                    if counter > args.patience:
                        break
                print('best acc test %f best acc val %f' % (best_acc_test,
                                                            acc_val))
                print('record %s' % record_file)
                with open(record_file, 'a') as f:
                    f.write('step %d best %f final %f \n' % (step,
                                                            best_acc_test,
                                                            acc_val))
                G.train()
                F1.train()
                #saving model as a checkpoint dict having many things
                if args.save_check:
                    print('saving model')
                    is_best = True if counter==0 else False
                    save_mymodel(args, {
                     'step': step,
                     'arch': args.net,
                     'G_state_dict': G.state_dict(),
                     'F1_state_dict': F1.state_dict(),
                     'best_acc_test': best_acc_test,
                     'optimizer_g' : optimizer_g.state_dict(),
                     'optimizer_f' : optimizer_f.state_dict(),
                     }, is_best)	

    # defining the function for in training validation and testing

    def test(loader):
        G.eval()
        F1.eval()
        test_loss = 0
        correct = 0
        size = 0
        num_class = len(class_list)
        output_all = np.zeros((0, num_class))

        # Setting the loss function to be used for the classification loss
        if args.loss == 'CE':
            criterion = nn.CrossEntropyLoss().to(device)
        if args.loss == 'FL':
            criterion = FocalLoss(alpha = 1, gamma = 1).to(device)
        if args.loss == 'CBFL':
            # Calculating the list having the number of examples per class which is going to be used in the CB focal loss
            beta = 0.99
            effective_num = 1.0 - np.power(beta, class_num_list)
            per_cls_weights = (1.0 - beta) / np.array(effective_num)
            per_cls_weights = per_cls_weights / np.sum(per_cls_weights) * len(class_num_list)
            per_cls_weights = torch.FloatTensor(per_cls_weights).to(device)
            criterion = CBFocalLoss(weight=per_cls_weights, gamma=0.5).to(device)

        confusion_matrix = torch.zeros(num_class, num_class)
        with torch.no_grad():
            for batch_idx, data_t in enumerate(loader):
                im_data_t.data.resize_(data_t[0].size()).copy_(data_t[0])
                gt_labels_t.data.resize_(data_t[1].size()).copy_(data_t[1])
                feat = G(im_data_t)
                output1 = F1(feat)
                output_all = np.r_[output_all, output1.data.cpu().numpy()]
                size += im_data_t.size(0)
                pred1 = output1.data.max(1)[1]
                for t, p in zip(gt_labels_t.view(-1), pred1.view(-1)):
                    confusion_matrix[t.long(), p.long()] += 1
                correct += pred1.eq(gt_labels_t.data).cpu().sum()
                test_loss += criterion(output1, gt_labels_t) / len(loader)
        np.save("cf_target.npy",confusion_matrix)
        #print(confusion_matrix)
        print('\nTest set: Average loss: {:.4f}, '
            'Accuracy: {}/{} F1 ({:.0f}%)\n'.
            format(test_loss, correct, size,
                    100. * correct / size))
        return test_loss.data, 100. * float(correct) / size

    print("Starting stage 2 training of the model ...")
    train()
  
# Invoking the main function here
if __name__ == "__main__":
    main()
