import os
import time
import argparse
import numpy as np
from glob import glob
from tqdm import tqdm

import torch
import torch.nn as nn
from torch import optim

from utils.functions import dict_to_str
from utils.metricsTop import MetricsTop

class EF_LSTM():
    def __init__(self, args):
        self.args = args
        self.criterion = nn.CrossEntropyLoss()
        self.metrics = MetricsTop().getMetics(args.datasetName)

    def do_train(self, model, dataloader):
        optimizer = optim.Adam(model.parameters(), lr=self.args.learning_rate, weight_decay=self.args.weight_decay)
        # initilize results
        epochs, best_epoch = 0, 0
        epoch_results = {
            'train': [],
            'valid': [],
            'test': []
        }
        min_or_max = 'min' if self.args.KeyEval in ['Loss'] else 'max'
        best_valid = 1e8 if min_or_max == 'min' else 0
        # loop util earlystop
        while True: 
            epochs += 1
            # train
            y_pred, y_true = [], []
            losses = []
            model.train()
            train_loss = 0.0
            with tqdm(dataloader['train']) as td:
                for batch_data in td:
                    vision = batch_data['vision'].to(self.args.device)
                    audio = batch_data['audio'].to(self.args.device)
                    text = batch_data['text'].to(self.args.device)
                    labels = batch_data['labels']["M"].to(self.args.device).view(-1).long()
                    # clear gradient
                    optimizer.zero_grad()
                    # forward
                    outputs = model(text, audio, vision)
                    # compute loss
                    loss = self.criterion(outputs["M"], labels)
                    # backward
                    loss.backward()
                    # update
                    optimizer.step()
                    # store results
                    train_loss += loss.item()
                    y_pred.append(outputs["M"].detach().cpu())
                    y_true.append(labels.detach().cpu())
            train_loss = train_loss / len(dataloader['train'])
            pred, true = torch.cat(y_pred), torch.cat(y_true)
            train_results = self.metrics(pred, true)
            train_results["Loss"] = train_loss
            epoch_results['train'].append(train_results)
            print("TRAIN-(%s) (%d/%d)>> loss: %.4f " % (self.args.modelName, \
                epochs - best_epoch, epochs, train_loss) + dict_to_str(train_results))
            # validation
            val_results = self.do_test(model, dataloader['valid'], mode="VAL")
            test_results = self.do_test(model, dataloader['test'], mode="TEST")
            epoch_results['valid'].append(val_results)
            epoch_results['test'].append(test_results)

            cur_valid = val_results[self.args.KeyEval]
            # save best model
            isBetter = cur_valid <= best_valid if min_or_max == 'min' else cur_valid >= best_valid
            # save best model
            if isBetter:
                best_valid, best_epoch = cur_valid, epochs
                # save model
                torch.save(model.cpu().state_dict(), self.args.model_save_path)
                model.to(self.args.device)
            # early stop
            if epochs - best_epoch >= self.args.early_stop:
                return epoch_results

    def do_test(self, model, dataloader, mode="VAL", need_details=False):
        model.eval()
        y_pred, y_true = [], []
        eval_loss = 0.0
        if need_details:
            ids, sample_results = [], []
            all_labels = []
            features = {
                "Feature_T": [],
                "Feature_A": [],
                "Feature_V": [],
                "Feature_M": [],
            }
        with torch.no_grad():
            with tqdm(dataloader) as td:
                for batch_data in td:
                    vision = batch_data['vision'].to(self.args.device)
                    audio = batch_data['audio'].to(self.args.device)
                    text = batch_data['text'].to(self.args.device)
                    labels = batch_data['labels']["M"].to(self.args.device).view(-1).long()
                    outputs = model(text, audio, vision)

                    if need_details:
                        ids.extend(batch_data['id'])
                        for item in features.keys():
                            features[item].append(outputs[item].cpu().detach().numpy())
                        all_labels.extend(labels.cpu().detach().tolist())
                        preds = outputs["M"].cpu().detach().numpy()
                        test_preds_i = np.argmax(preds, axis=1)
                        sample_results.extend(test_preds_i)

                    loss = self.criterion(outputs["M"], labels)
                    eval_loss += loss.item()
                    y_pred.append(outputs["M"].detach().cpu())
                    y_true.append(labels.detach().cpu())
        eval_loss = eval_loss / len(dataloader)

        pred, true = torch.cat(y_pred), torch.cat(y_true)
        results = self.metrics(pred, true)
        print(mode+"-(%s)" % self.args.modelName + " >> loss: %.4f " % \
                eval_loss + dict_to_str(results))
        results["Loss"] = eval_loss

        if need_details:
            results["Ids"] = ids
            results["SResults"] = sample_results
            for k in features.keys():
                features[k] = np.concatenate(features[k], axis=0)
            results['Features'] = features
            results['Labels'] = all_labels

        return results