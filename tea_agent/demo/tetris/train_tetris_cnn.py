#!/usr/bin/env python3
"""
Tetris CNN Trainer (Lightweight)
"""
import os, time, argparse
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, regularizers, callbacks
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BOARD_H, BOARD_W = 20, 10
NUM_CLASSES = 4
ACTION_NAMES = ['left', 'right', 'rotate', 'none']

def build_light_cnn():
    """Lightweight CNN for CPU training."""
    inp = keras.Input(shape=(BOARD_H, BOARD_W, 1))
    x = layers.Conv2D(16, (3,3), padding='same', activation='relu',
                      kernel_regularizer=regularizers.l2(1e-3))(inp)
    x = layers.MaxPooling2D((2,2))(x)
    x = layers.Conv2D(32, (3,3), padding='same', activation='relu',
                      kernel_regularizer=regularizers.l2(1e-3))(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(32, activation='relu',
                     kernel_regularizer=regularizers.l2(1e-3))(x)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(NUM_CLASSES, activation='softmax')(x)
    model = keras.Model(inp, out, name='tetris_cnn_light')
    return model

def plot_history(history, save_path):
    fig, axes = plt.subplots(1, 2, figsize=(14,5))
    axes[0].plot(history.history['accuracy'], label='train')
    axes[0].plot(history.history['val_accuracy'], label='val')
    axes[0].set_title('Accuracy'); axes[0].legend(); axes[0].grid(alpha=0.3)
    axes[1].plot(history.history['loss'], label='train')
    axes[1].plot(history.history['val_loss'], label='val')
    axes[1].set_title('Loss'); axes[1].legend(); axes[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    print(f'Plot: {save_path}')
    plt.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', required=True)
    p.add_argument('--epochs', type=int, default=15)
    p.add_argument('--batch', type=int, default=512)
    p.add_argument('--lr', type=float, default=5e-3)
    p.add_argument('--output', default='tetris_cnn_model')
    args = p.parse_args()
    
    print('='*60)
    print('Tetris CNN Trainer (Lightweight)')
    print('='*60)
    
    # Load
    data = np.load(args.data)
    imgs, acts = data['images'], data['actions']
    print(f'Data: {len(imgs)} samples, shape {imgs.shape}')
    
    # Class weights for imbalance (none=79.8%)
    counts = np.bincount(acts)
    total = len(acts)
    class_weight = {i: total/(NUM_CLASSES*counts[i]) for i in range(NUM_CLASSES)}
    print(f'Class weights: {class_weight}')
    
    # Preprocess
    x = imgs[..., np.newaxis].astype(np.float32)
    y = acts.astype(np.int32)
    x_train, x_val, y_train, y_val = train_test_split(
        x, y, test_size=0.15, random_state=42, stratify=y)
    print(f'Train: {len(x_train)} | Val: {len(x_val)}')
    
    # Build model
    model = build_light_cnn()
    model.summary()
    
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=args.lr),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy'],
    )
    
    # Callbacks
    model_path = f'{args.output}.keras'
    cb_list = [
        callbacks.ModelCheckpoint(model_path, save_best_only=True,
                                   monitor='val_accuracy', mode='max'),
        callbacks.EarlyStopping(monitor='val_accuracy', patience=6,
                                 restore_best_weights=True),
        callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5,
                                     patience=3, min_lr=1e-6),
    ]
    
    # Train
    print('\nTraining...')
    t0 = time.time()
    history = model.fit(x_train, y_train,
                        validation_data=(x_val, y_val),
                        epochs=args.epochs,
                        batch_size=args.batch,
                        class_weight=class_weight,
                        callbacks=cb_list,
                        verbose=2)
    t = time.time()-t0
    print(f'Time: {t:.1f}s ({t/60:.1f}min)')
    
    # Load best
    if os.path.exists(model_path):
        model = keras.models.load_model(model_path)
        print(f'Loaded best: {model_path}')
    
    # Evaluate
    y_pred = model.predict(x_val, verbose=0)
    y_pred_cls = np.argmax(y_pred, axis=1)
    print('\nClassification Report:')
    print(classification_report(y_val, y_pred_cls,
                                target_names=ACTION_NAMES))
    
    # Confusion matrix
    cm = confusion_matrix(y_val, y_pred_cls)
    print('Confusion Matrix:')
    print(f'{"":10s}', ''.join(f'{n:8s}' for n in ACTION_NAMES))
    for i, n in enumerate(ACTION_NAMES):
        print(f'{n:8s}', ''.join(f'{cm[i,j]:<8d}' for j in range(NUM_CLASSES)))
    
    # Save
    final_path = f'{args.output}_final.keras'
    model.save(final_path)
    print(f'Saved: {final_path}')
    
    # TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite = converter.convert()
    tflite_path = f'{args.output}.tflite'
    with open(tflite_path, 'wb') as f:
        f.write(tflite)
    print(f'TFLite: {tflite_path} ({len(tflite)/1024:.1f} KB)')
    
    # Plot
    plot_history(history, f'{args.output}_history.png')
    print('Done!')

if __name__ == '__main__':
    main()
