"""Library for 1D neural networks using Theano: supports convolutional and
fully connected layers"""

import cPickle
import gzip
import numpy as np
import theano
import theano.tensor as T
from layers1d import ConvPoolLayer, FullyConnectedLayer
from nnet_functions import abs_error_cost, relu


# Configure floating point numbers for Theano
theano.config.floatX = "float32"
    

class NNet1D(object):
    """A neural network implemented for 1D neural networks in Theano"""
    def __init__(self, seed, datafile, batch_size, learning_rate, momentum,
                 cost_fn=relu):
        """Initialize network: seed the random number generator, load the
        datasets, and store model parameters"""
        # Store random number generator, batch size, learning rate and momentum
        self.rng = np.random.RandomState(seed)
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.momentum = momentum
        
        # Store cost function
        self.cost_fn = cost_fn
        
        # Initialize layers in the neural network
        self.layers = []
        
        # Input and output matrices (2D)
        self.x = T.matrix('x')
        self.y = T.matrix('y')
        
        # Split into training, validation, and testing datasets
        datasets = NNet1D.load_data(datafile)
        self.train_set_x, self.train_set_y = datasets[0]
        self.valid_set_x, self.valid_set_y = datasets[1]
        self.test_set_x, self.test_set_y = datasets[2]
        
        # Determine input and output sizes
        self.n_in = self.train_set_x.get_value(borrow=True).shape[1]
        self.n_out = self.train_set_y.get_value(borrow=True).shape[1]
        
        # Determine number of batches for each dataset
        self.n_train_batches = self.train_set_x.get_value(borrow=True).shape[0]
        self.n_train_batches /= batch_size
        self.n_valid_batches = self.valid_set_x.get_value(borrow=True).shape[0]
        self.n_valid_batches /= batch_size
        self.n_test_batches = self.test_set_x.get_value(borrow=True).shape[0]
        self.n_test_batches /= batch_size
        
    def add_conv_pool_layer(self, filters, filter_length, poolsize, activ_fn=relu):
        """Add a convolutional layer to the network"""
        # If first layer, use x as input
        if len(self.layers) == 0:
            input = self.x
            input_number = 1
            input_length = self.n_in
        
        # If previous layer is convolutional, use its output as input
        elif isinstance(self.layers[-1], ConvPoolLayer):
            input = self.layers[-1].output
            input_number = self.layers[-1].output_shape[1]
            input_length = self.layers[-1].output_shape[3]
        
        # If previous layer is fully connected, use its output as input
        elif isinstance(self.layers[-1], FullyConnectedLayer):
            input = self.layers[-1].output
            input_number = 1
            input_length = self.layers[-1].output_shape
        
        # Otherwise raise error
        else:
            raise TypeError("Invalid previous layer")
            
        # Add the layer
        layer = ConvPoolLayer(self.rng, input, input_length, self.batch_size,
                              filters, filter_length, input_number, poolsize,
                              activ_fn)
        self.layers.append(layer)
        
    def add_fully_connected_layer(self, output_length=None, activ_fn=None):
        """Add a fully connected layer to the network"""
        # If output_length is None, use self.n_out
        if output_length is None:
            output_length = self.n_out
        
        # If first layer, use x as input
        if len(self.layers) == 0:
            input = self.x
            input_length = self.n_in
        
        # If previous layer is convolutional, use its flattened output as input
        elif isinstance(self.layers[-1], ConvPoolLayer):
            input = self.layers[-1].output.flatten(2)
            output_shape = self.layers[-1].output_shape
            input_length = self.layers[-1].filter_shape[1] * output_shape[3]
        
        # If previous layer is fully connected, use its output as input
        elif isinstance(self.layers[-1], FullyConnectedLayer):
            input = self.layers[-1].output
            input_length = self.layers[-1].output_shape
        
        # Otherwise raise error
        else:
            raise TypeError("Invalid previous layer")
            
        # Add the layer
        layer = FullyConnectedLayer(self.rng, input, input_length,
                                    output_length, self.batch_size,
                                    self.cost_fn, activ_fn)
        self.layers.append(layer)
    
    def build(self):
        """Build the neural network from the given layers"""
        # Last layer must be fully connected and produce correct output size
        assert isinstance(self.layers[-1], FullyConnectedLayer)
        assert self.layers[-1].output_shape == self.n_out
        
        # Cost function is last layer's output cost
        self.cost = self.layers[-1].cost(self.y)
        
        # Keep a count of the number of training steps, train/valid errors
        self.epochs = 0
        self.train_errors = []
        self.valid_errors = []
        
        # Index for batching
        i = T.lscalar()
        
        # Batching for training set
        batch_size = self.batch_size
        givens = {self.x: self.train_set_x[i*batch_size:(i+1)*batch_size],
                  self.y: self.train_set_y[i*batch_size:(i+1)*batch_size]}
        
        # Stochastic gradient descent algorithm for training function
        params = [param for layer in self.layers for param in layer.params]
        updates = self.gradient_updates_momentum(params)
        
        # Make Theano training function
        self.train_model = theano.function([i], self.cost, updates=updates,
                                           givens=givens)
        
        # Batching for validation set
        givens = {self.x: self.valid_set_x[i*batch_size:(i+1)*batch_size],
                  self.y: self.valid_set_y[i*batch_size:(i+1)*batch_size]}
        
        # Make Theano validation function
        self.validate_model = theano.function([i], self.cost, givens = givens)
        
        # Batching for testing set
        givens = {self.x: self.test_set_x[i*batch_size:(i+1)*batch_size],
                  self.y: self.test_set_y[i*batch_size:(i+1)*batch_size]}
        
        # Make Theano testing function
        self.test_model = theano.function([i], self.cost, givens=givens)
        
        # Shared variables for output
        x = T.matrix()
        givens = {self.x: x}
        output = self.layers[-1].output
        
        # Make Theano output function
        self.output_function = theano.function([x], output, givens=givens)

    @staticmethod
    def load_data(filename):
        """Load the datasets from file with filename"""
        # Unpickle raw datasets from file as numpy arrays
        with gzip.open(filename, 'rb') as file:
            train_set, valid_set, test_set = cPickle.load(file)
    
        def shared_dataset(data_xy, borrow=True):
            """Load the dataset data_xy into shared variables"""
            # Split into input and output
            data_x, data_y = data_xy
            
            # Store as numpy arrays with Theano data types
            shared_x_array = np.asarray(data_x, dtype=theano.config.floatX)
            shared_y_array = np.asarray(data_y, dtype=theano.config.floatX)
            
            # Create Theano shared variables
            shared_x = theano.shared(shared_x_array, borrow=borrow)
            shared_y = theano.shared(shared_y_array, borrow=borrow)
            
            # Return shared variables
            return shared_x, shared_y
    
        # Return the resulting shared variables
        return [shared_dataset(train_set), shared_dataset(valid_set),
                shared_dataset(test_set)]
        
    def print_computational_graph(self, outfile, format="svg"):
        """Print computational graph for producing output to filename in
        specified format"""
        return theano.printing.pydotprint(self.output_function, format=format,
                                          outfile=outfile)

    def train(self):
        """Apply one training step of the network and return average training
        and validation error"""
        self.epochs += 1
        train_errors = [self.train_model(i)
                        for i in xrange(self.n_train_batches)]
        valid_errors = [self.validate_model(i)
                        for i in xrange(self.n_valid_batches)]
        self.train_errors.append(np.mean(train_errors))
        self.valid_errors.append(np.mean(valid_errors))
        return np.mean(train_errors), np.mean(valid_errors)
            
    def test_error(self):
        """Return average test error from the network"""
        test_errors = [self.test_model(i) for i in range(self.n_test_batches)]
        return np.mean(test_errors)
    
    def gradient_updates_momentum(self, params):
        """Return the updates necessary to implement momentum"""
        updates = []
        for param in params:
            # Update parameter
            param_update = theano.shared(param.get_value()*0.,
                                         broadcastable=param.broadcastable)
            updates.append((param, param - self.learning_rate*param_update))
            
            # Store gradient with exponential decay
            grad = T.grad(self.cost, param)
            updates.append((param_update,
                            self.momentum*param_update +
                            (1 - self.momentum)*grad))
            
        # Return the updates
        return updates
    
    def output(self, x):
        """Return output from an input to the network"""
        # Copy x to own its data
        x = np.copy(x)
        
        # Store x's initial size
        x_size = x.shape[0]
        
        # Resize x
        x.resize(self.batch_size, self.n_in)
        
        # Return the output in x's initial size
        return self.output_function(x)[:x_size]
