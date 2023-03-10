# -*- coding: utf-8 -*-
"""bc5cdr_cnn.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1vajfVXkNFTG5IaVN0Wj197CpLJB1pbDX

# Setup
"""

from collections import defaultdict
import re
import json
import tensorflow as tf
import numpy as np
import sklearn
import pickle
import matplotlib as mpl
import matplotlib.pyplot as plt
from tensorflow.keras import layers
from tensorflow.keras.preprocessing.text import Tokenizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from google.colab import drive
drive.mount('/content/drive')

!pip install nltk
import nltk
from nltk import word_tokenize
nltk.download('punkt')

!pip install scispacy
!pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_core_sci_sm-0.5.1.tar.gz

import spacy
from spacy.lang.en import English
nlp = spacy.load("en_core_sci_sm")

"""# Data Preprocessing

## Import data
"""

class Reader:
    def __init__(self, file_name):
        self.file_name = file_name

    def read(self, **kwargs):
        """
        return raw data from input file
        :param kwargs:
        :return:
        """
        pass


class BioCreativeReader(Reader):
    def __init__(self, file_name):
        super().__init__(file_name)

        with open(file_name, 'r') as f:
            self.lines = f.readlines()

    def read(self):
        """
        :return: dict of abstract's: {<id>: {'t': <string>, 'a': <string>}}
        """
        regex = re.compile(r'^([\d]+)\|([at])\|(.+)$', re.U | re.I)
        abstracts = defaultdict(dict)

        for line in self.lines:
            matched = regex.match(line)
            if matched:
                data = matched.groups()
                abstracts[data[0]][data[1]] = data[2]

        return abstracts

    def read_entity(self):
        """
        :return: dict of entity's: {<id>: [(pmid, start, end, content, type, id)]}
        """
        regex = re.compile(r'^(\d+)\t(\d+)\t(\d+)\t([^\t]+)\t(\S+)\t(\S+)', re.U | re.I)

        ret = defaultdict(list)

        for line in self.lines:
            matched = regex.search(line)
            if matched:
                data = matched.groups()
                ret[data[0]].append(tuple([data[0], int(data[1]), int(data[2]), data[3], data[4], data[5]]))

        return ret

    def read_relation(self):
        """
        :return: dict of relation's: {<id>: [(pmid, type, chem_id, dis_id)]}
        """
        regex = re.compile(r'^([\d]+)\t(CID)\t([\S]+)\t([\S]+)$', re.U | re.I)
        ret = defaultdict(list)

        for line in self.lines:
            matched = regex.match(line)
            if matched:
                data = matched.groups()
                ret[data[0]].append(data)

        return ret

bc5cdr_reader = BioCreativeReader("/content/cdr_full.txt")
bc5cdr_abstract = bc5cdr_reader.read()
bc5cdr_entity = bc5cdr_reader.read_entity()
bc5cdr_relation = bc5cdr_reader.read_relation()

def remove(index, a, b, c):
    a.pop(index)
    b.pop(index)
    c.pop(index)

remove('16298782', bc5cdr_abstract, bc5cdr_entity, bc5cdr_relation)
remove('16574713', bc5cdr_abstract, bc5cdr_entity, bc5cdr_relation)

"""## Data grouping"""

def wordTokenizer(text):
    doc = nlp(text)
    return [token.text for token in doc]

def sentTokenizer(sent):
    doc = nlp(sent)
    return [sent.text for sent in doc.sents]

def POSTagger(text):
    doc = nlp(text)
    return [token.pos_ for token in doc]

def dependencyTagger(text):
    doc = nlp(text)
    return [token.dep_ for token in doc]

def IOBTagger(text):
    doc = nlp(text)
    return [token.ent_iob_ for token in doc]

def position(text, offset):
    doc = nlp(text)

    for token in doc:
        if offset >= token.idx and offset < token.idx + len(token):
            return token.i + 1
    return None

abstract = []
entity = []
relation = []
pair = []
sentences = []

for index in bc5cdr_abstract:

    sent_abstract_split = []
    sent_abstract = []
    sent_entity = []
    sent_relation = []
    sent_pair = []

    text = bc5cdr_abstract[index]['t'] + " " + bc5cdr_abstract[index]['a']

    # Add abstract of splitted sentences
    sent_abstract_split = sentTokenizer(bc5cdr_abstract[index]['a'])
    sent_abstract_split.insert(0, bc5cdr_abstract[index]['t'])
    sentences.append(sent_abstract_split)

    for i in range(len(sent_abstract_split)):
        tmp = (index + "_" + str(i), sent_abstract_split[i])
        sent_abstract.append(tmp)

    # Add entities of splitted sentences
    sent_length = []
    length_counter = 0
    sent_pos = 0

    for i in sent_abstract:
        if sent_pos == 0:
            length_counter += len(i[1])
            sent_length.append(length_counter)
            sent_pos += 1
        else:
            length_counter += len(i[1]) + 1
            sent_length.append(length_counter)
            sent_pos += 1

    for i in bc5cdr_entity[index]:
        sent_pos = 0
        place = i[1]
        while place > sent_length[sent_pos]:
            sent_pos += 1
        tmp = list(i)
        tmp[0] = index + "_" + str(sent_pos)
        if sent_pos > 0:
            tmp[1] -= sent_length[sent_pos - 1] + 1
            tmp[2] -= sent_length[sent_pos - 1] + 1
        i = tuple(tmp)
        sent_entity.append(i)

    # Add relations of splitted sentences
    sent_relation = []
    for r in bc5cdr_relation[index]:
        for e1 in sent_entity:
            if e1[5] == r[2]:
                for e2 in sent_entity:
                    if (e2[5] == r[3]) and (e2[0] == e1[0]):
                        tmp = list(r)
                        tmp[0] = e1[0]
                        tmp = tuple(tmp)
                        sent_relation.append(tmp)

    # Add chemical-disease pairs and labels to document data
    for e1 in sent_entity:
        if e1[4] == 'Chemical':
            for e2 in sent_entity:
                if e1[0] == e2[0] and e2[4] == 'Disease':
                    tmp = (e1[0], e1[1], e1[2], e1[3], e1[4], e1[5], 
                          e2[1], e2[2], e2[3], e2[4], e2[5], 0)
                    sent_pair.append(tmp)

    for i in range(len(sent_pair)): 
        for r in sent_relation:
            if sent_pair[i][5] == r[2] and sent_pair[i][10] == r[3]:
                sent_pair[i] = list(sent_pair[i])
                sent_pair[i][11] = 1
                sent_pair[i] = tuple(sent_pair[i])

    # Add data of document to dataset
    abstract.append(sent_abstract)
    entity.append(sent_entity)
    relation.append(sent_relation)
    pair.append(sent_pair)

# Add the sentence to dataset
for i in pair:
    for j in range(len(i)):
        for a in abstract:
            for b in a:
                if i[j][0] == b[0]:
                    i[j] = list(i[j])
                    i[j].insert(1, b[1])
                    i[j] = tuple(i[j])

# Change offset in dataset by position of word
for p in pair:
    for i in range(len(p)):
        p[i] = list(p[i])
        p[i][2] = position(p[i][1], p[i][2])
        p[i][3] = position(p[i][1], p[i][3] - 1)
        p[i][7] = position(p[i][1], p[i][7])
        p[i][8] = position(p[i][1], p[i][8] - 1)
        p[i] = tuple(p[i])

"""## Word Parsing"""

word_parsed = []
for p in pair:
    for j in p:
        tokens = wordTokenizer(j[1])
        word_parsed.append(tokens)

"""## Positional Tagging"""

# Generate a list of position embeddings given position of two entities
def positionGenerator(sent, e1_s, e1_e, e2_s, e2_e):
    tmp1_list = []
    tmp2_list = []
    for i in range(len(wordTokenizer(sent))):
        if i + 1 < e1_s:
            tmp1_list.append(str(i + 1 - e1_s))
        elif e1_s <= i + 1 and i + 1 <= e1_e:
            tmp1_list.append(str(0))
        elif i + 1 > e1_e:
            tmp1_list.append(str(i + 1 - e1_e))
    
    for i in range(len(wordTokenizer(sent))):
        if i + 1 < e2_s:
            tmp2_list.append(str(i + 1 - e2_s))
        elif e2_s <= i + 1 and i + 1 <= e2_e:
            tmp2_list.append(str(0))
        elif i + 1 > e2_e:
            tmp2_list.append(str(i + 1 - e2_e))
    
    tmp_list = []

    for i in range(len(tmp1_list)):
        tmp_list.append([tmp1_list[i], tmp2_list[i]])

    return tmp_list

position_embedding = []
for p in pair:
    for i in range(len(p)):
        position_embedding.append(positionGenerator(p[i][1], p[i][2], p[i][3], p[i][7], p[i][8]))

p1 = []
p2 = []
for i in position_embedding:
    tmp_p1 = []
    tmp_p2 = []
    for j in i:
        tmp_p1.append(j[0])
        tmp_p2.append(j[1])
    p1.append(tmp_p1)
    p2.append(tmp_p2)

"""## POS Tagging"""

pos_tagging = []

for p in pair:
    for j in p:
        tokens = POSTagger(j[1])
        pos_tagging.append(tokens)

"""## Dependency Tagging"""

dep_tagging = []

for p in pair:
    for j in p:
        tokens = dependencyTagger(j[1])
        dep_tagging.append(tokens)

"""## IOB Tagging

"""

iob_tagging = []

for p in pair:
    for j in p:
        tokens = IOBTagger(j[1])
        iob_tagging.append(tokens)

"""## Getting labels"""

labels = []
for i in pair:
    for j in i:
        labels.append(j[12])

"""## Saving all variables for model

"""

with open('/content/drive/MyDrive/my_variables.pkl', 'wb') as f:
    pickle.dump([word_parsed, p1, p2, pos_tagging, dep_tagging, iob_tagging, labels], f)

"""# Tokenization and create vocabulary"""

with open('/content/drive/MyDrive/my_variables.pkl', 'rb') as f:
    word_parsed, p1, p2, pos_tagging, dep_tagging, iob_tagging, labels = pickle.load(f)

with open('/content/drive/MyDrive/my_variables_test.pkl', 'rb') as f:
    word_parsed_test, p1_test, p2_test, pos_tagging_test, dep_tagging_test, iob_tagging_test, labels_test = pickle.load(f)

class Tokenizer():
    def __init__(self, text):
        self.tokenizer = tf.keras.preprocessing.text.Tokenizer(
            filters = None,
            lower = False,
        )
        self.text = text
        self.word_dict = None

    def fit_on_texts(self):
        self.tokenizer.fit_on_texts(self.text)
        self.word_dict = self.tokenizer.word_index

words_list = word_parsed + word_parsed_test
word_tokenizer = Tokenizer(words_list)
word_tokenizer.fit_on_texts()
vocab = list(word_tokenizer.word_dict.keys())

w2v_path = '/content/drive/MyDrive/pm.wiki.vec'

word_vectors = {}

with open(w2v_path, 'r') as f:

    f.readline()

    for line in f:
        tokens = line.strip().split()
        if len(tokens) == 301:
            word = tokens[0]
            if word in vocab:
                vector = [x for x in tokens[1:]]
                word_vectors[word] = vector

for word in vocab:
    if word not in word_vectors.keys():
        word_vectors[word] = [0] * 300

for word in word_vectors:
    for i in range(len(word_vectors[word])):
            word_vectors[word][i] = float(word_vectors[word][i])

embedding_matrix = np.zeros((len(word_tokenizer.word_dict), 300))
counter = 0

for word in word_tokenizer.word_dict:
    embedding_matrix[counter] = word_vectors[word]
    counter += 1

with open('/content/drive/MyDrive/word_vectors.pkl', 'wb') as f:
    pickle.dump([word_tokenizer, word_vectors, embedding_matrix], f)

"""# Loading variables"""

with open('/content/drive/MyDrive/my_variables.pkl', 'rb') as f:
    word_parsed, p1, p2, pos_tagging, dep_tagging, iob_tagging, labels = pickle.load(f)

with open('/content/drive/MyDrive/my_variables_test.pkl', 'rb') as f:
    word_parsed_test, p1_test, p2_test, pos_tagging_test, dep_tagging_test, iob_tagging_test, labels_test = pickle.load(f)

with open('/content/drive/MyDrive/word_vectors.pkl', 'rb') as f:
    word_tokenizer, word_vectors, embedding_matrix = pickle.load(f)

def display(tmp):
    tmp = 0
    for i in range(len(word_parsed[tmp])):
        print("{:5}{:5}{:5}{:5}{:5}{:5}".format(word_parsed[tmp][i], p1[tmp][i], p2[tmp][i], pos_tagging[tmp][i], dep_tagging[tmp][i], iob_tagging[tmp][i]))

"""# Tokenizing features"""

class Tokenizer():
    def __init__(self, text):
        self.tokenizer = tf.keras.preprocessing.text.Tokenizer(
            filters = None,
            lower = False,
        )
        self.text = text
        self.word_dict = None

    def fit_on_texts(self):
        self.tokenizer.fit_on_texts(self.text)
        self.word_dict = self.tokenizer.word_index

p1_tokenizer = Tokenizer(p1)
p2_tokenizer = Tokenizer(p2)
pos_tokenizer = Tokenizer(pos_tagging)
dep_tokenizer = Tokenizer(dep_tagging)
iob_tokenizer = Tokenizer(iob_tagging)
p1_tokenizer.fit_on_texts()
p2_tokenizer.fit_on_texts()
pos_tokenizer.fit_on_texts()
dep_tokenizer.fit_on_texts()
iob_tokenizer.fit_on_texts()

word_parsed = word_tokenizer.tokenizer.texts_to_sequences(word_parsed)
p1 = p1_tokenizer.tokenizer.texts_to_sequences(p1)
p2 = p2_tokenizer.tokenizer.texts_to_sequences(p2)
pos_tagging = pos_tokenizer.tokenizer.texts_to_sequences(pos_tagging)
dep_tagging = dep_tokenizer.tokenizer.texts_to_sequences(dep_tagging)
iob_tagging = iob_tokenizer.tokenizer.texts_to_sequences(iob_tagging)

"""# Padding and Concatenation"""

percentile = 95
sentence_lengths = [len(sentence) for sentence in word_parsed]
padding_length = int(np.percentile(sentence_lengths, percentile))

def padding(pad_list):
    return tf.keras.preprocessing.sequence.pad_sequences(
        pad_list,
        dtype='int',
        maxlen=padding_length,
        padding='post',
        truncating='post'
    )

word_parsed = padding(word_parsed)
p1 = padding(p1)
p2 = padding(p2)
pos_tagging = padding(pos_tagging)
dep_tagging = padding(dep_tagging)
iob_tagging = padding(iob_tagging)

embedding_matrix = np.vstack((np.zeros((1, 300)), embedding_matrix))

"""# Data Splitting"""

word_train, word_val, p1_train, p1_val, p2_train, p2_val, pos_train, pos_val, dep_train, dep_val, iob_train, iob_val, labels_train, labels_val = train_test_split(
    word_parsed, p1, p2, pos_tagging, dep_tagging, iob_tagging, labels, test_size=0.1, random_state=42)

pos = 0
neg = 0
total = 0

for i in labels_train:
    if i == 0:
        neg += 1
    else: 
        pos += 1
    
    total += 1


weight_for_0 = (1 / neg) * (total / 2.0)
weight_for_1 = (1 / pos) * (total / 2.0)

class_weight = {0: weight_for_0, 1: weight_for_1}

"""
# Model"""

input_name = [
    "word",
    "p1",
    "p2",
    "pos",
    "dep",
    "iob"
]

embedding_dims = [300, 30, 30, 30, 30, 10]

word_input = tf.keras.Input(
    shape=(padding_length,), name="word"
)

p1_input = tf.keras.Input(
    shape=(padding_length,), name="p1"
)

p2_input = tf.keras.Input(
    shape=(padding_length,), name="p2"
)

pos_input = tf.keras.Input(
    shape=(padding_length,), name="pos"
)

dep_input = tf.keras.Input(
    shape=(padding_length,), name="dep"
)

iob_input = tf.keras.Input(
    shape=(padding_length,), name="iob"
)

word_features = layers.Embedding(len(word_tokenizer.word_dict) + 1,
                                 embedding_dims[0],
                                 weights=[embedding_matrix],
                                 trainable=True,
                                 mask_zero=True)(word_input)

p1_features = layers.Embedding(len(p1_tokenizer.word_dict) + 1, 
                               embedding_dims[1], 
                               mask_zero=True)(p1_input)

p2_features = layers.Embedding(len(p2_tokenizer.word_dict) + 1, 
                               embedding_dims[2], 
                               mask_zero=True)(p2_input)

pos_features = layers.Embedding(len(pos_tokenizer.word_dict) + 1, 
                               embedding_dims[3], 
                               mask_zero=True)(pos_input)
                              
dep_features = layers.Embedding(len(dep_tokenizer.word_dict) + 1, 
                               embedding_dims[4], 
                               mask_zero=True)(dep_input)

iob_features = layers.Embedding(len(iob_tokenizer.word_dict) + 1, 
                               embedding_dims[5], 
                               mask_zero=True)(iob_input)

x = layers.concatenate([word_features, 
                        p1_features,
                        p2_features,
                        pos_features, 
                        dep_features,
                        iob_features], 
                       axis=-1)

x = tf.expand_dims(x, axis = -1)

x1 = layers.Conv2D(filters=100, 
                  kernel_size=(10, 430), 
                  activation='relu')(x)

x2 = layers.Conv2D(filters=100, 
                  kernel_size=(20, 430), 
                  activation='relu')(x)

x3 = layers.Conv2D(filters=100, 
                  kernel_size=(30, 430), 
                  activation='relu')(x)

x4 = layers.Conv2D(filters=100, 
                  kernel_size=(40, 430), 
                  activation='relu')(x)

x1 = layers.MaxPooling2D(1, 54)(x1)
x2 = layers.MaxPooling2D(1, 44)(x2)
x3 = layers.MaxPooling2D(1, 34)(x3)
x4 = layers.MaxPooling2D(1, 24)(x4)

x1 = layers.Flatten()(x1)
x2 = layers.Flatten()(x2)
x3 = layers.Flatten()(x3)
x4 = layers.Flatten()(x4)

output = layers.concatenate([x1, x2, x3, x4], axis=-1)
output = layers.Dropout(0.8)(output)
output = layers.Dense(1, activation='sigmoid')(output)

model = tf.keras.models.Model(
    inputs=[word_input, 
            p1_input, 
            p2_input, 
            pos_input, 
            dep_input, 
            iob_input], 
    outputs=output)

model.summary()
tf.keras.utils.plot_model(model, "model.png", show_shapes=True)

"""# Training"""

metrics = [
      tf.keras.metrics.BinaryAccuracy(name='accuracy'),
      tf.keras.metrics.Precision(name='precision'),
      tf.keras.metrics.Recall(name='recall'),
      tf.keras.metrics.AUC(name='auc'),
      tf.keras.metrics.AUC(name='prc', curve='PR'), # precision-recall curve
]

model.compile(optimizer='adam',
              loss=tf.keras.losses.BinaryCrossentropy(from_logits=False),
              metrics=metrics)

mpl.rcParams['figure.figsize'] = (12, 10)
colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

def plot_metrics(history):
  metrics = ['loss', 'accuracy', 'precision', 'recall']
  for n, metric in enumerate(metrics):
    name = metric.replace("_"," ").capitalize()
    plt.subplot(2,2,n+1)
    plt.plot(history.epoch, history.history[metric], color=colors[0], label='Train')
    plt.plot(history.epoch, history.history['val_'+metric],
             color=colors[0], linestyle="--", label='Val')
    plt.xlabel('Epoch')
    plt.ylabel(name)
    if metric == 'loss':
      plt.ylim([0, plt.ylim()[1]])
    elif metric == 'auc':
      plt.ylim([0.8,1])
    else:
      plt.ylim([0,1])

    plt.legend()

history = model.fit(
    [word_train, 
     p1_train, 
     p2_train, 
     pos_train, 
     dep_train,
     iob_train], 
    labels_train, 
    epochs=100, 
    batch_size=32,
    validation_data=([word_val, 
                      p1_val, 
                      p2_val, 
                      pos_val, 
                      dep_val, 
                      iob_val], 
                     labels_val),
    class_weight=class_weight)

plot_metrics(history)