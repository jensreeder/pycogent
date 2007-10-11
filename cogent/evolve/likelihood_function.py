#!/usr/bin/env python

import random, numpy

from cogent.core.alignment import Alignment
from cogent.recalculation.array import DictArrayTemplate
from cogent.evolve.simulate import AlignmentEvolver, randomSequence
from cogent.util import parallel, table

__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007, The Cogent Project"
__credits__ = ["Gavin Huttley", "Andrew Butterfield", "Peter Maxwell",
                    "Matthew Wakefield", "Rob Knight", "Brett Easton"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"

# cogent.evolve.parameter_controller.LikelihoodParameterController tells the
# recalculation framework to use this subclass rather than the generic
# recalculation Calculator.  It adds methods which are useful for examining
# the parameter, psub, mprob and likelihood values after the optimisation is
# complete.

class LikelihoodFunction(object):
    def setpar(self, param_name, value, edge=None, **scope):
        # for tests only
        return self.setParamRule(param_name, edge=edge, value=value, is_const=True, **scope)
    
    def testfunction(self):
        # for tests only
        return self.getLogLikelihood()
    
    def getParamValue(self, *args, **kw):
        return self.real_par_controller.getParamValue(*args, **kw)
    
    def getParamInterval(self, *args, **kw):
        return self.real_par_controller.getParamInterval(*args, **kw)
    
    def getParamValueDict(self, *args, **kw):
        return self.real_par_controller.getParamValueDict(*args, **kw)
    
    def getParamNames(self, *args, **kw):
        return self.real_par_controller.getParamNames(*args, **kw)
    
    def getUsedDimensions(self, param_name, **kw):
        return self.real_par_controller.getUsedDimensions(param_name, **kw)
    
    def getLogLikelihood(self):
        return self.real_par_controller.getFinalResult()
    
    def getNumFreeParams(self):
        """returns the number of free parameters."""
        return self.real_par_controller.getNumFreeParams()
    
    def getPsubForEdge(self, name):
        array = self.getParamValue('psubs', edge=name)
        return DictArrayTemplate(self._motifs, self._motifs).wrap(array)
    
    def getFullLengthLikelihoods(self, locus=None):
        # XXX These will not really be full length if MPI is
        # being used!
        if self.bin_names and len(self.bin_names) > 1:
            root_lh = self.getParamValue('bindex', locus=locus)
            root_lhs = [self.getParamValue('lh', locus=locus, bin=bin) for
                bin in self.bin_names]
            return root_lh.getFullLengthLikelihoods(*root_lhs)
        else:
            root_lht = self.getParamValue('root', locus=locus)
            root_lh = self.getParamValue('lh', locus=locus)
            return root_lht.getFullLengthLikelihoods(root_lh)
    
    def reconstructAncestralSequences(self, locus=None):
        """returns a dict of DictArray objects containing probabilities
        of each alphabet state for each node in the tree.
        
        Arguments:
            - locus: a named locus"""
        result = {}
        array_template = None
        for restricted_edge in self._tree.getEdgeVector():
            if restricted_edge.istip():
                continue
            try:
                r = []
                for motif in range(len(self._motifs)):
                    self.setParamRule('fixed_motif', value=motif,
                            edge=restricted_edge.Name, locus=locus,
                            is_const=True)
                    likelihoods = self.getFullLengthLikelihoods(locus=locus)
                    r.append(likelihoods)
                    if array_template is None:
                        array_template = DictArrayTemplate(
                                likelihoods.shape[0], self._motifs)
            finally:
                self.setParamRule('fixed_motif', value=-1,
                        edge=restricted_edge.Name, locus=locus,
                        is_const=True)
            # dict of site x motif arrays
            result[restricted_edge.Name] = array_template.wrap(
                    numpy.transpose(numpy.asarray(r)))
        return result
    
    def likelyAncestralSeqs(self, locus=None):
        """Returns the most likely reconstructed ancestral sequences as an
        alignment.
        
        Arguments:
            - locus: a named locus"""
        prob_array = self.reconstructAncestralSequences(locus=locus)
        seqs = []
        for edge, probs in prob_array.items():
            seq = []
            for row in probs:
                by_p = [(p,state) for state, p in row.items()]
                seq.append(max(by_p)[1])
            seqs += [(edge, self.model.MolType.makeSequence("".join(seq)))]
        return Alignment(data = seqs, MolType = self.model.MolType)
    
    def getBinProbs(self, locus=None):
        hmm = self.getParamValue('bindex', locus=locus)
        lhs = [self.getParamValue('lh', locus=locus, bin=bin)
                for bin in self.bin_names]
        array = hmm.getPosteriorProbs(*lhs)
        return DictArrayTemplate(self.bin_names, array.shape[1]).wrap(array)
    
    def _valuesForDimension(self, dim):
        # in support of __str__
        if dim == 'edge':
            result = [e.Name for e in self._tree.getEdgeVector()
                    if not e.isroot()]
        elif dim == 'bin':
            result = self.bin_names[:]
        elif dim == 'locus':
            result = self.locus_names[:]
        elif dim == 'motif':
            result = self._motifs
        else:
            raise KeyError, dim
        return result
    
    def _valuesForDimensions(self, dims):
        # in support of __str__
        result = [[]]
        for dim in dims:
            new_result = []
            for r in result:
                for cat in self._valuesForDimension(dim):
                    new_result.append(r+[cat])
            result = new_result
        return result
    
    def __str__(self):
        if not self._name:
            title = 'Likelihood Function Table'
        else:
            title = self._name
        result = [title]
        group = {}
        for param in self.getParamNames():
            dims = tuple(self.getUsedDimensions(param))
            if dims not in group:
                group[dims] = []
            group[dims].append(param)
        table_order = group.keys()
        for table_dims in table_order:
            raw_table = self.getParamValueDict(
                dimensions=table_dims, params=group[table_dims])
            param_names = group[table_dims]
            param_names.sort()
            if table_dims == ('edge',):
                if 'length' in param_names:
                    param_names.remove('length')
                    param_names.insert(0, 'length')
                raw_table['parent'] = dict([(e.Name, e.Parent.Name)
                        for e in self._tree.getEdgeVector()
                        if not e.isroot()])
                param_names.insert(0, 'parent')
            list_table = []
            heading_names = list(table_dims) + param_names
            row_order = self._valuesForDimensions(table_dims)
            for scope in row_order:
                row = {}
                for param in param_names:
                    d = raw_table[param]
                    for part in scope:
                        d = d[part]
                    row[param] = d
                row.update(dict(zip(table_dims, scope)))
                row = [row[k] for k in heading_names]
                list_table.append(row)
            result.append(
                str(
                    table.Table(
                        heading_names, list_table,
                        max_width = 80, row_ids = True)))
        return '\n'.join(result)
    
    def getAnnotatedTree(self):
        d = self.getStatisticsAsDict(with_parent_names=False)
        tree = self._tree.deepcopy()
        for edge in tree.getEdgeVector():
            if edge.Name == 'root':
                continue
            for par in d:
                edge.params[par] = d[par][edge.Name]
        return tree
    
    def getMotifProbs(self, bin=None, locus=None):
        motif_probs_array = self.getParamValue(
                self._mprobs_name, bin=bin, locus=locus)
        return DictArrayTemplate(self._motifs).wrap(motif_probs_array)
        #return dict(zip(self._motifs, motif_probs_array))
    
    def getBinPriorProbs(self, locus=None):
        bin_probs_array = self.getParamValue('bprobs', locus=locus)
        return DictArrayTemplate(self.bin_names).wrap(bin_probs_array)
    
    def getScaledLengths(self, predicate, bin=None, locus=None):
        """A dictionary of {scale:{edge:length}}"""
        if not hasattr(self._model, 'getScaledLengthsFromQ'):
            return {}
        
        def valueOf(param, **kw):
            return self.getParamValue(param, locus=locus, **kw)
        
        if bin is None:
            bin_names = self.bin_names
        else:
            bin_names = [bin]
        
        if len(bin_names) == 1:
            bprobs = [1.0]
        else:
            bprobs = valueOf('bprobs')
        
        mprobs = [valueOf(self._mprobs_name, bin=b) for b in bin_names]
        
        scaled_lengths = {}
        for edge in self._tree.getEdgeVector():
            if edge.isroot():
                continue
            Qs = [valueOf('Qd', bin=b, edge=edge.Name).Q for b in bin_names]
            length = valueOf('length', edge=edge.Name)
            scaled_lengths[edge.Name] = length * self._model.getScaleFromQs(
                    Qs, bprobs, mprobs, predicate)
        return scaled_lengths
    
    def getStatisticsAsDict(self, with_parent_names=True,
                with_edge_names=False):
        """Returns a dictionary containing the statistics for each edge of the
        tree, and any other information provided by the substitution model. The
        dictionary is keyed at the top-level by parameter name, and then by
        edge.name.
        
        Arguments:
            - with_edge_names: if True, an ordered list of edge names is
              included under the top-level key 'edge.names'. Default is
              False.
        """
        
        stats_dict = self.getParamValueDict(['edge'])
        
        for predicate in self.model.scale_masks:
            stats_dict[predicate] = self.getScaledLengths(predicate)
        
        edge_vector = [e for e in self._tree.getEdgeVector() if not e.isroot()]
        
        # do the edge names
        if with_parent_names:
            parents = {}
            for edge in edge_vector:
                if edge.Parent.isroot():
                    parents[edge.Name] = "root"
                else:
                    parents[edge.Name] = str(edge.Parent.Name)
            stats_dict["edge.parent"] = parents
        
        if with_edge_names:
            stats_dict['edge.name'] = (
                    [e.Name for e in edge_vector if e.istip()] +
                    [e.Name for e in edge_vector if not e.istip()])
        
        return stats_dict
    
    # For tests.  Compat with old LF interface
    def setName(self, name):
        self._name = name
    
    def getName(self):
        return self._name or 'unnamed'
    
    def simulateAlignment(self, sequence_length=None, random_series=None,
            exclude_internal=True, locus=None, seed=None, root_sequence=None):
        """
        Returns an alignment of simulated sequences with key's corresponding to
        names from the current attached alignment.
        
        Arguments:
            - sequence_length: the legnth of the alignment to be simulated,
              default is the length of the attached alignment.
            - random_series: a random number generator.
            - exclude_internal: if True, only sequences for tips are returned.
            - root_sequence: a sequence from which all others evolve.
        """
        
        if sequence_length is None:
            lht = self.getParamValue('lht', locus=locus)
            sequence_length = len(lht.index)
            leaves = self.getParamValue('leaf_likelihoods', locus=locus)
            orig_ambig = {} #alignment.getPerSequenceAmbiguousPositions()
            for (seq_name, leaf) in leaves.items():
                orig_ambig[seq_name] = leaf.getAmbiguousPositions()
        else:
            orig_ambig = {}
        
        mprobs = self.getMotifProbs(locus=locus)
        
        if random_series is None:
            random_series = random.Random()
            random_series.seed(seed)
            parallel.sync_random(random_series)
        
        def psub_for(edge, bin):
            return self.getParamValue('psubs',
                    edge=edge, bin=bin, locus=locus)
        
        if len(self.bin_names) > 1:
            hmm = self.getParamValue('bdist', locus=locus)
            site_bins = hmm.emit(sequence_length, random_series)
        else:
            site_bins = numpy.zeros([sequence_length], int)
        
        evolver = AlignmentEvolver(random_series, orig_ambig, exclude_internal,
                self.bin_names, site_bins, psub_for, self._motifs)
        
        if root_sequence is not None: # we convert to a vector of motifs
            if isinstance(root_sequence, str):
                root_sequence = self._model.MolType.makeSequence(root_sequence)
            motif_len = self._model.getAlphabet().getMotifLen()
            root_sequence = root_sequence.getInMotifSize(motif_len)
        else:
            root_sequence = randomSequence(
                random_series, mprobs, sequence_length)
        
        simulated_sequences = evolver(self._tree, root_sequence)
        
        return Alignment(
                data = simulated_sequences,
                MolType = self._model.MolType)
        
    