import argparse
import glob
import json
import math
import os
import sys

import matplotlib as mpl
from keras.applications.densenet import DenseNet121, preprocess_input
from keras.layers import Dense, GlobalAveragePooling2D
from keras.models import Model
from keras.optimizers import SGD
from keras.preprocessing.image import ImageDataGenerator

mpl.use('TkAgg')

IM_WIDTH = 224  # 299 for InceptionV3, 224 for Densenet121
IM_HEIGHT = IM_WIDTH
NB_EPOCHS = 5
BAT_SIZE = 32
FC_SIZE = 1024
NB_LAYERS_TO_FREEZE = math.ceil(429 * 0.5)  # len(Densenet121.layers) = 429


def get_nb_files(directory):
    """Get number of files by searching directory recursively"""
    if not os.path.exists(directory):
        return 0
    cnt = 0
    for r, dirs, files in os.walk(directory):
        for dr in dirs:
            cnt += len(glob.glob(os.path.join(r, dr + "/*")))
    return cnt


def setup_to_transfer_learn(model, base_model):
    """Freeze all layers and compile the model"""
    for layer in base_model.layers:
        layer.trainable = False
    model.compile(optimizer='rmsprop', loss='categorical_crossentropy', metrics=['accuracy'])


def add_new_last_layer(base_model, nb_classes):
    """Add last layer to the convnet

    Args:
      base_model: keras model excluding top
      nb_classes: # of classes

    Returns:
      new keras model with last layer
    """
    x = base_model.output
    x = GlobalAveragePooling2D()(x)
    x = Dense(FC_SIZE, activation='relu')(x)  # new FC layer, random init
    predictions = Dense(nb_classes, activation='softmax')(x)  # new softmax layer
    model = Model(input=base_model.input, output=predictions)
    return model


def setup_to_finetune(model):
    """Freeze the bottom NB_IV3_LAYERS and retrain the remaining top layers.

    note: NB_IV3_LAYERS corresponds to the top 2 inception blocks in the inceptionv3 arch

    Args:
      model: keras model
    """
    for layer in model.layers[:NB_LAYERS_TO_FREEZE]:
        layer.trainable = False
    for layer in model.layers[NB_LAYERS_TO_FREEZE:]:
        layer.trainable = True
    model.compile(optimizer=SGD(lr=0.0001, momentum=0.9), loss='categorical_crossentropy', metrics=['accuracy'])


def train(args):
    """Use transfer learning and fine-tuning to train a network on a new dataset"""
    nb_train_samples = get_nb_files(args.train_dir)
    nb_classes = len(glob.glob(args.train_dir + "/*"))
    nb_val_samples = get_nb_files(args.val_dir)
    nb_epoch = int(args.nb_epoch)
    batch_size = int(args.batch_size)

    # data prep
    datagen = ImageDataGenerator(
        preprocessing_function=preprocess_input
    )

    train_generator = datagen.flow_from_directory(
        args.train_dir,
        target_size=(IM_WIDTH, IM_HEIGHT),
        batch_size=batch_size,
        class_mode='categorical'
    )

    validation_generator = datagen.flow_from_directory(
        args.val_dir,
        target_size=(IM_WIDTH, IM_HEIGHT),
        batch_size=batch_size,
        class_mode='categorical'
    )

    with open('validation_class_indices.json', 'w') as fp:
        json.dump(validation_generator.class_indices, fp, sort_keys=True, indent=4)

    # setup model
    base_model = DenseNet121(weights='imagenet', include_top=False)  # include_top=False excludes final FC layer
    model = add_new_last_layer(base_model, nb_classes)

    # transfer learning
    setup_to_transfer_learn(model, base_model)

    history_tl = model.fit_generator(
        train_generator,
        epochs=nb_epoch,
        steps_per_epoch=nb_train_samples / batch_size,
        validation_data=validation_generator,
        validation_steps=nb_val_samples / batch_size,
        class_weight='auto')

    # fine-tuning
    setup_to_finetune(model)

    nb_epoch = 1
    history_ft = model.fit_generator(
        train_generator,
        epochs=nb_epoch,
        steps_per_epoch=nb_train_samples / batch_size,
        validation_data=validation_generator,
        validation_steps=nb_val_samples / batch_size,
        class_weight='auto')

    model.save(args.output_model_file)

    if args.plot:
        plot_training(history_ft)


def plot_training(history):
    acc = history.history['acc']
    val_acc = history.history['val_acc']
    loss = history.history['loss']
    val_loss = history.history['val_loss']
    epochs = range(len(acc))

    plt.plot(epochs, acc, 'r.')
    plt.plot(epochs, val_acc, 'r')
    plt.title('Training and validation accuracy')

    plt.figure()
    plt.plot(epochs, loss, 'r.')
    plt.plot(epochs, val_loss, 'r-')
    plt.title('Training and validation loss')
    plt.show()


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--train_dir", default="train")
    a.add_argument("--val_dir", default="validate")
    a.add_argument("--nb_epoch", default=NB_EPOCHS)
    a.add_argument("--batch_size", default=BAT_SIZE)
    a.add_argument("--output_model_file", default="dense121-ft.model")
    a.add_argument("--plot", action="store_true")

    args = a.parse_args()
    if args.train_dir is None or args.val_dir is None:
        a.print_help()
        sys.exit(1)

    if (not os.path.exists(args.train_dir)) or (not os.path.exists(args.val_dir)):
        print("directories do not exist")
        sys.exit(1)

    train(args)

    print("Done ;) ")
    sys.exit(0)
