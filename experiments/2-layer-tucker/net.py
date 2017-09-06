import numpy as np
import tensorflow as tf
import math
import sys


sys.path.append('../../../')
import tensornet

NUM_CLASSES = 10
IMAGE_SIZE = 28#32
IMAGE_DEPTH = 1#3
IMAGE_PIXELS = IMAGE_SIZE * IMAGE_SIZE * IMAGE_DEPTH

opts = {}
opts['inp_modes_1'] = np.array([4, 7, 4, 7], dtype='int32')
opts['out_modes_1'] = np.array([3, 4, 5, 5], dtype='int32')
#opts['ranks_1'] = np.array([3, 3, 3, 3], dtype='int32')
#opts['inp_modes_1'] = np.array([4, 4, 4, 4, 4, 3], dtype='int32')
#opts['out_modes_1'] = np.array([8, 8, 8, 8, 8, 8], dtype='int32')
#opts['ranks_1'] = np.array([1, 3, 3, 3, 3, 3, 1], dtype='int32')

opts['inp_modes_2'] = opts['out_modes_1']
opts['out_modes_2'] = np.array([2, 2, 5, 5], dtype='int32')
#opts['ranks_2'] = np.array([3, 3, 3, 3], dtype='int32')
#opts['inp_modes_2'] = opts['out_modes_1']
#opts['out_modes_2'] = np.array([4, 4, 4, 4, 4, 4], dtype='int32')
#opts['ranks_2'] = np.array([1, 3, 3, 3, 3, 3, 1], dtype='int32')


opts['use_dropout'] = True
opts['learning_rate_init'] = 0.05
opts['learning_rate_decay_steps'] = 2000
opts['learning_rate_decay_weight'] = 0.64

def placeholder_inputs():
    """Generate placeholder variables to represent the input tensors.
            
    Returns:
        images_ph: Images placeholder.
        labels_ph: Labels placeholder.
        train_phase_ph: Train phase indicator placeholder.
    """
    # Note that the shapes of the placeholders match the shapes of the full
    # image and label tensors, except the first dimension is now batch_size
    # rather than the full size of the train or test data sets.
    images_ph = tf.placeholder(tf.float32, shape=(None, IMAGE_PIXELS), name='placeholder/images')
    labels_ph = tf.placeholder(tf.int32, shape=(None), name='placeholder/labels')
    train_phase_ph = tf.placeholder(tf.bool, name='placeholder/train_phase')
    return images_ph, labels_ph, train_phase_ph

def inference(images, train_phase, new_opts):
    """Build the model up to where it may be used for inference.
    Args:
        images: Images placeholder.
        train_phase: Train phase placeholder
    Returns:
        logits: Output tensor with the computed logits.
    """
    tn_init = lambda dev: lambda shape: tf.truncated_normal(shape, stddev=dev)
    tu_init = lambda bound: lambda shape: tf.random_uniform(shape, minval = -bound, maxval = bound)

    dropout_rate = lambda p: (opts['use_dropout'] * (p - 1.0)) * tf.to_float(train_phase) + 1.0

    
    layers = []
    layers.append(images)    

    
    layers.append(tensornet.layers.tucker_dense(layers[-1],
                                     opts['inp_modes_1'],
                                     opts['out_modes_1'],
                                     new_opts['ranks_1'],
                                     3.0, #0.1
                                     'tucker_dense_' + str(len(layers)),
                                     use_biases=False))

    layers.append(tensornet.layers.batch_normalization(layers[-1],
                                                       [np.prod(opts['out_modes_1'])],
                                                       train_phase,
                                                       scope='BN_' + str(len(layers)),
                                                       ema_decay=0.8)) 
    
    layers.append(tf.nn.relu(layers[-1],
                             name='relu_' + str(len(layers))))
    layers.append(tf.nn.dropout(layers[-1],
                                dropout_rate(0.6),
                                name='dropout_' + str(len(layers))))

 
##########################################
    # from 2-layer tucker 
    layers.append(tensornet.layers.tucker_dense(layers[-1],
                                     opts['inp_modes_2'],
                                     opts['out_modes_2'],
                                     new_opts['ranks_2'],
                                     3.0, #0.07
                                     'tucker_dense_' + str(len(layers)),
                                     use_biases=False))

    layers.append(tensornet.layers.batch_normalization(layers[-1],
                                                       [np.prod(opts['out_modes_2'])],
                                                       train_phase,
                                                       scope='BN_' + str(len(layers)),
                                                       ema_decay=0.8)) 
 
    layers.append(tf.nn.relu(layers[-1],
                             name='relu_' + str(len(layers))))
    
    layers.append(tf.nn.dropout(layers[-1],
                                dropout_rate(0.6),
                                name='dropout_' + str(len(layers))))
    
##########################################

    layers.append(tensornet.layers.linear(layers[-1],                                          
                                          np.prod(opts['out_modes_2']),
                                          NUM_CLASSES,
                                          init=tn_init(2.0 / np.prod(opts['out_modes_2'])),
                                          scope='linear_' + str(len(layers))))

    return layers[-1]

def loss(logits, labels):
    """Calculates the loss from the logits and the labels.
    Args:
        logits: input tensor, float - [batch_size, NUM_CLASSES].
        labels: Labels tensor, int32 - [batch_size].
    Returns:
        loss: Loss tensor of type float.
    """
    # Convert from sparse integer labels in the range [0, NUM_CLASSES)
    # to 1-hot dense float vectors (that is we will have batch_size vectors,
    # each with NUM_CLASSES values, all of which are 0.0 except there will
    # be a 1.0 in the entry corresponding to the label).
    batch_size = tf.size(labels)
    labels = tf.expand_dims(labels, 1)
    indices = tf.expand_dims(tf.range(0, batch_size), 1)
    concated = tf.concat(1, [indices, labels])
    onehot_labels = tf.sparse_to_dense(concated,
                                       tf.pack([batch_size, NUM_CLASSES]), 1.0, 0.0)
    

    cross_entropy = tf.nn.softmax_cross_entropy_with_logits(logits,
                                                            onehot_labels,
                                                            name='xentropy')
    loss = tf.reduce_mean(cross_entropy, name='loss')
    tf.scalar_summary('loss', loss, name='summary/loss')
    return loss
    
def training(loss):
    """Sets up the training Ops.    
    Creates an optimizer and applies the gradients to all trainable variables.
    The Op returned by this function is what must be passed to the
    `sess.run()` call to cause the model to train.
    Args:
        loss: Loss tensor, from loss().       
    Returns:
        train_op: The Op for training.
    """
    # Create a variable to track the global step.
    global_step = tf.Variable(0, name='global_step', trainable=False)
    learning_rate = tf.train.exponential_decay(opts['learning_rate_init'],
                                               global_step,
                                               opts['learning_rate_decay_steps'],
                                               opts['learning_rate_decay_weight'],
                                               staircase=True,
                                               name='learning_rate')
    tf.scalar_summary('learning_rate', learning_rate, name='summary/learning_rate')
    # Create the gradient descent optimizer with the given learning rate.
    optimizer = tf.train.GradientDescentOptimizer(learning_rate, name='optimizer')
        
    grads_and_vars = optimizer.compute_gradients(loss)
    train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step, name='train_op')
    return train_op

def evaluation(logits, labels):
    """Evaluate the quality of the logits at predicting the label.
    Args:
        logits: Logits tensor, float - [batch_size, NUM_CLASSES].
        labels: Labels tensor, int32 - [batch_size], with values in the
        range [0, NUM_CLASSES).
    Returns:
        A scalar int32 tensor with the number of examples (out of batch_size)
        that were predicted correctly.
    """
    # For a classifier model, we can use the in_top_k Op.
    # It returns a bool tensor with shape [batch_size] that is true for
    # the examples where the label's is was in the top k (here k=1)
    # of all logits for that example.
    correct_flags = tf.nn.in_top_k(logits, labels, 1)
    # Return the number of true entries.
    correct_count = tf.reduce_sum(tf.cast(correct_flags, tf.int32), name='correct_count')
    return correct_count


def build(new_opts={}):
    """ Build graph
        Args:
            new_opts: dict with additional opts, which will be added to opts dict/
    """
    opts.update(new_opts)
    images_ph, labels_ph, train_phase_ph = placeholder_inputs()
    logits = inference(images_ph, train_phase_ph, new_opts)
    loss_out = loss(logits, labels_ph)
    train = training(loss_out)
    eval_out = evaluation(logits, labels_ph)
