import numpy as np
from scipy.optimize import fmin_l_bfgs_b
from scipy.special import logsumexp
from sklearn.metrics import precision_recall_fscore_support, precision_recall_curve, auc 
from document import document

class model():
    def __init__(self, data, is_lifelong, alpha):
        self.IS_LIFELONG = is_lifelong
        
        self.cue = [] #contain word_str s
        self.DUBPLICATE_CUE = alpha
        self.MAX_CUE_EACH_CLASS = 50
        
        self.data = data
        
        self.labels = self.data.LABELS # C set [0,1]
        self.label_count = len(self.labels)
        
        self.V = self.data.cp_str_2_int.values()  # V set [0,1,2....V-1] 
        self.V_count = len(self.V)
        
        # Model parameters
        # lambda shape = matrix CxV
        self.lmbda = np.zeros( self.label_count* self.V_count)            
            
    def change_domain(self, new_data):
        
        print 'Change to new train domain', new_data.train_domain
        # add old data to new data
        # recalculate cp_str_2_int, V
        # represent doc with new dictionary
        
        new_train_docs = []
        new_cp_str_2_int = {}
        new_cp_int_2_str = {}
        
        #FIXME - duplicate code
        past_pos_docs = self.data.get_positive_train_docs()
        for line in past_pos_docs:
            origin_doc_str = line       
            doc = {}
            [sentence, label_str] = line.strip('\n\t ').split(',')
            sentence = sentence.strip('\t\n ')
                
            label_str = label_str.strip('\t\n ')
            label_id = int(label_str)
            if label_id != 1:
                print 'ERROR. label_id %d must be 1. it is pos. Check data.get_pos_doc method'%(label_id)
                exit(1)
                
            tokens = sentence.split()
            for token_str in tokens:
                token_id = new_cp_str_2_int.get(token_str)
                if token_id == None: # not in context_predicate_map string - id
                    token_id = len(new_cp_str_2_int)
                    new_cp_str_2_int[token_str] = token_id
                    new_cp_int_2_str[token_id] = token_str
                    
                if token_id not in doc: # check if in doc or not
                    doc[token_id] = 1
                else :
                    doc[token_id] += 1
                
            aDoc = document(doc, label_id, origin_doc_str)
            new_train_docs.append(aDoc)
        
        for new_doc in new_data.train:
            origin_doc_str = new_doc.origin_str
            line = new_doc.origin_str       
            doc = {}
            [sentence, label_str] = line.strip('\n\t ').split(',')
            sentence = sentence.strip('\t\n ')
                
            label_str = label_str.strip('\t\n ')
            label_id = int(label_str)
            if label_id not in self.labels:
                print 'ERROR. label_id not found'
                exit(1)
                
            tokens = sentence.split()
            for token_str in tokens:
                token_id = new_cp_str_2_int.get(token_str)
                if token_id == None: # not in context_predicate_map string - id
                    token_id = len(new_cp_str_2_int)
                    new_cp_str_2_int[token_str] = token_id
                    new_cp_int_2_str[token_id] = token_str
                    
                if token_id not in doc: # check if in doc or not
                    doc[token_id] = 1
                else :
                    doc[token_id] += 1
                
            aDoc = document(doc, label_id, origin_doc_str)
            new_train_docs.append(aDoc)
        
        new_data.train = new_train_docs
        new_data.cp_str_2_int = new_cp_str_2_int
        new_data.cp_int_2_str = new_cp_int_2_str
        
        
        # update cue for new train_data
        cue_ids = []
        for cue_str in self.cue:
            cue_id = new_data.cp_str_2_int.get(cue_str)
            if cue_id != None:
                cue_ids.append(cue_id)
        
        for doc in new_data.train:
            for cue_id in cue_ids:
                if cue_id in doc.cp_ids_counts.keys():
                    doc.cp_ids_counts[cue_id] += self.DUBPLICATE_CUE
            doc.length = sum(doc.cp_ids_counts.values())

        
        # ---------update test doc with new dictionary in train domain
        new_test_doc_presenations = []
        for doc in new_data.test:
            line = doc.origin_str
            cp_id_counts = {}
            [sentence, label_str] = line.strip('\n\t ').split(',')
            sentence = sentence.strip('\t\n ')
                
            label_str = label_str.strip('\t\n ')
            label_id = int(label_str)
            if label_id not in new_data.LABELS:
                print 'ERROR in input file. balel_id %d not found in LABELS%s'%(label_id, new_data.LABELS)
                exit(1)
                
            tokens = sentence.split()
            for token_str in tokens:
                token_id = new_data.cp_str_2_int.get(token_str)
                if token_id == None: # not in context_predicate_map string - id
                    continue
                if token_id not in cp_id_counts: # check if in doc or not
                    cp_id_counts[token_id] = 1
                else :
                    cp_id_counts[token_id] += 1
            
            aDoc = document(cp_id_counts, label_id, doc.origin_str)
            new_test_doc_presenations.append(aDoc)
            
        new_data.test = new_test_doc_presenations
        
        self.data = new_data
        
        # update self.V, self.V, self.lmbda s.t new data
        self.V = self.data.cp_str_2_int.values()  # V set [0,1,2....V-1] 
        self.V_count = len(self.V)
        self.lmbda = np.zeros( self.label_count* self.V_count)            

        
    def softmax(self,x):
        '''
        input x:ndarray
        output e^x /sum(e^x) (trick to avoid overflow)
        '''
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum()

    # REMOVEME                            
    def compute_contidional_prob(self, label_idx, doc, lmbda):
        '''
        compute P(c|d) = exp(sum_i lambda_i * f_i(c,d)) / sum_c exp(sum_i lambda_i * f_i(c,d))
                                    i = (w,c) for w \in V, c \in C
        '''
        temp = np.zeros(self.label_count)
        for label_ in self.labels:
            temp[label_] = self.compute_sum_features(doc, label_, lmbda)
        temp = self.softmax(temp)
        return temp[label_idx]
    
    def compute_doc_feature(self, doc, word_id):
        '''
        compute f_i(c,d) = f_(w,c') (c,d) = N(w,d)/N(d) if c == c' or 0 if c!= c'
        '''
        return 1.0 * doc.cp_ids_counts[word_id] / doc.length
    
    def compute_sum_features(self, doc, label_idx, lmbda):
        '''
        compute sum_i lambda[i]* f_i (doc, label_idx)
        '''
        _sum = 0.0
        word_ids = doc.cp_ids_counts.keys()
        for word_id in word_ids:
            _sum += lmbda[label_idx*self.V_count + word_id] * self.compute_doc_feature(doc, word_id)
        return _sum
    
    def compute_log_li_grad(self, lmbda):        
        '''
        compute log_li and its gradient
        log_li = sum_d (log P(c(d)|d) with c(d) is human label of document d
        grad_i = grad(lambda_i) = sum_d ( f_i(c(d),d) + (sum_c f_i(c,d)*exp(sum_i lambda_i * f_i(c,d))) / (sum_c exp(sum_i lambda_i * f_i(c,d))) )
        NOTE: 
            *) log_li is computed directly follow the above formular
            *) grad:
                for each document:
                    update grad_i accumulating in this document
        '''

        log_li = 0.0
        grad = np.zeros(lmbda.shape)

        for doc in self.data.train:
            ########### compute log_li #############
            doc_log_li = 0.0
            ep_1 = self.compute_sum_features(doc, doc.human_label, lmbda)
            
            temp = np.zeros(self.label_count)           
            for label_idx in self.labels:
                temp[label_idx] = self.compute_sum_features(doc, label_idx, lmbda)                
            
            doc_log_li = ep_1 - logsumexp(temp)
            log_li += doc_log_li
            
            ###### Update feature_idx with word_id in docs ##########
            word_ids = doc.cp_ids_counts.keys()
            # update feature idx with d.humanlabel
            for word_id in word_ids:
                feature_idx = doc.human_label * self.V_count + word_id
                grad[feature_idx] += self.compute_doc_feature(doc, word_id)
            
            #NOTE - This is the same in computing doc_log_li, but remained here for clear
            temp = np.zeros(self.label_count)                
            for label_idx in self.labels:
                temp[label_idx] = self.compute_sum_features(doc, label_idx, lmbda)
            temp = self.softmax(temp)            
            
            for word_id in word_ids:
                for label_idx in self.labels:
                    feature_idx = label_idx * self.V_count + word_id
                    grad[feature_idx] -= self.compute_doc_feature(doc, word_id) * temp[label_idx]
            
        return -log_li, np.negative(grad) #negate it because fmin_l_bfgs_b is minimization function
            
    def train(self):
        '''
        Using fmin_l_bfgs_b to maxmimum log likelihood
        NOTE: fmin_l_bfgs_b returns 3 values
        '''
        print "Training max_ent with LBFGS algorithm. Change iprint = 99 to more logs..."
        self.lmbda, log_li, dic = fmin_l_bfgs_b(self.compute_log_li_grad, self.lmbda, iprint = 0)
    
        if self.IS_LIFELONG == True:
            self.update_cue()
    
    def update_cue(self):
        print 'Updating cue...\n'
        cue_ids = []
        
        # cue for only positive 
#         lmbda_pos_idx = self.lmbda[1 * self.V_count: 1 * self.V_count + self.V_count]
#         temp = np.argpartition(-lmbda_pos_idx, self.MAX_CUE_EACH_CLASS)
#         max_idxes = temp[:self.MAX_CUE_EACH_CLASS]
#         for idx in max_idxes:    
#             cue_ids.append(idx)
#         

        for label_idx in self.labels:
            lmbda_label_idx = self.lmbda[label_idx * self.V_count: label_idx * self.V_count + self.V_count]
            temp = np.argpartition(-lmbda_label_idx, self.MAX_CUE_EACH_CLASS)
            max_idxes = temp[:self.MAX_CUE_EACH_CLASS]
            for idx in max_idxes:    
                cue_ids.append(idx)

        
        
        cue_strs = []
        for cue_id in cue_ids:
            cue_str = self.data.cp_int_2_str.get(cue_id)
            if cue_str == None:
                print "ERROR: cue str not found in data.dictionary"
                exit(1)
            cue_strs.append(cue_str)     
                    
        for cue_str in cue_strs:
            if cue_str not in self.cue:
                self.cue.append(cue_str)
                        
    def inference_doc(self, doc):
        '''
            return c_star = argmax_c P(c|d)
        '''
        temp = np.zeros(self.label_count)
        for label_ in self.labels:
            temp[label_] = self.compute_sum_features(doc, label_, self.lmbda)
        temp = self.softmax(temp)
        return np.argmax(temp)

        
    def inference(self):
        for doc in self.data.test:
            doc.model_label = self.inference_doc(doc)
    
    def validate(self):
                
        print 'Result in train domain : ', self.data.train_domain, '/ test domain: ', self.data.test_domain
        total_test_count = len(self.data.test)
        neg_count = 0
        for doc in self.data.test:
            if doc.human_label == 0:
                neg_count += 1
        print '#doc tests: ', total_test_count, '\t# neg_docs: ', neg_count, '\t#pos_docs', total_test_count-neg_count        
        
        model_labels = [doc.model_label for doc in self.data.test]
        human_labels = [doc.human_label for doc in self.data.test]
        
        prec, recall, _ = precision_recall_curve(human_labels, model_labels)
        auc_metric = auc(recall, prec)
        print 'AUC: ', auc_metric
        precision, recall, fscore, support = precision_recall_fscore_support(human_labels, model_labels)
        
        print 'PRECISION: {}'.format(precision), '\tmean', np.mean(precision)
        print 'RECALL: {}'.format(recall), '\tmean', np.mean(recall)
        print 'FSCORE: {}'.format(fscore), '\tmean', np.mean(fscore)
        print 'SUPPORT: {}'.format(support), '\n'
        
    def save_model(self):
        print 'saving model...'
        
        # lambda
        lambda_file = './Data/FOLDS/TIMERUN' + self.data.fold + '/' + self.data.train_domain + '_lambda.txt'
        fout = open(lambda_file, 'w')
        for label_idx in self.data.LABELS:
            for w in xrange(self.V_count):
                fout.write(str(self.lmbda[label_idx * self.V_count + w]) + ' ')
            fout.write('\n')
        fout.close()
        
        # vocab for lambda
        vocab_file = './Data/FOLDS/TIMERUN' + self.data.fold + '/' + self.data.train_domain + '_vocab.txt'
        fout = open(vocab_file, 'w')
        for cp_str in self.data.cp_str_2_int.keys():
            cp_id = self.data.cp_str_2_int.get(cp_str)
            fout.write(str(cp_id) + " " + cp_str + '\n')
        fout.close()
        
        print 'saved model in ./Data/FOLDS/TIMERUN' + self.data.fold  + '\n'

        
