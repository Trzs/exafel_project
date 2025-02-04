from __future__ import division
from cctbx.array_family import flex
from libtbx import group_args
import os,math
#
# List of consensus functions to be implemented
# 1. unit cell
# 2. orientational
# 3. spot clique
#

def get_dij_ori(cryst1, cryst2, is_reciprocal=True):
  '''
  Takes in 2 dxtbx crystal models, returns the distance between the 2 models in crystal
  space. Currently the distance is defined as the Z-score difference as implemented in
  cctbx/uctbx
  Info regarding some params in best_similarity_transformation after discussion with NKS
  fractional_length_tolerance :: could have value 1 or 200 ??
  unimodular_generator_range = to keep the volume to be 1. If volume doubles on change of basis, make it 2

  '''
  from scitbx.math import flex
  from cctbx_orientation_ext import crystal_orientation
  cryst1_ori = crystal_orientation(cryst1.get_A(), is_reciprocal)
  cryst2_ori = crystal_orientation(cryst2.get_A(), is_reciprocal)
  try:
    best_similarity_transform = cryst2_ori.best_similarity_transformation(
        other = cryst1_ori, fractional_length_tolerance = 1.00,
        unimodular_generator_range=1)
    cryst2_ori_best=cryst2_ori.change_basis(best_similarity_transform)
  except Exception as e:
    cryst2_ori_best = cryst2_ori
  #print 'difference z-score = ', cryst1_ori.difference_Z_score(cryst2_ori_best)
  return cryst1_ori.difference_Z_score(cryst2_ori_best)

def get_gaussian_rho(Dij, d_c):
  NN = Dij.focus()[0]
  rho = flex.double(NN)
  mu = flex.mean(Dij.as_1d())
  sigma = flex.mean_and_variance(Dij.as_1d()).unweighted_sample_standard_deviation()
  for i in range(NN):
    for j in range(NN):
      z = (Dij[i*NN + j]-mu)/sigma
      print (z,'AA')
      rho[i] += math.exp(-z*z)
  return rho;

class clustering_manager(group_args):
  def __init__(self, **kwargs):
    group_args.__init__(self, **kwargs)
    print ('finished Dij, now calculating rho_i and density')
    from xfel.clustering import Rodriguez_Laio_clustering_2014 as RL
    R = RL(distance_matrix = self.Dij, d_c = self.d_c)
    #from IPython import embed; embed(); exit()
    #from clustering.plot_with_dimensional_embedding import plot_with_dimensional_embedding
    #plot_with_dimensional_embedding(1-self.Dij/flex.max(self.Dij), show_plot=True)
    self.rho = rho = R.get_rho()
    ave_rho = flex.mean(rho.as_double())
    NN = self.Dij.focus()[0]
    i_max = flex.max_index(rho)
    delta_i_max = flex.max(flex.double([self.Dij[i_max,j] for j in range(NN)]))
    rho_order = flex.sort_permutation(rho, reverse=True)
    rho_order_list = list(rho_order)
    self.delta = delta = R.get_delta(rho_order=rho_order, delta_i_max=delta_i_max)
    cluster_id = flex.int(NN, -1) # -1 means no cluster
    delta_order = flex.sort_permutation(delta, reverse=True)
    MAX_PERCENTILE_RHO = self.max_percentile_rho # cluster centers have to be in the top percentile
    n_cluster = 0
#
    pick_top_solution=False
    rho_stdev = flex.mean_and_variance(rho.as_double()).unweighted_sample_standard_deviation()
    delta_stdev = flex.mean_and_variance(delta).unweighted_sample_standard_deviation()
    if rho_stdev !=0.0 and delta_stdev !=0:
      rho_z=(rho.as_double()-flex.mean(rho.as_double()))/(rho_stdev)
      delta_z=(delta-flex.mean(delta))/(delta_stdev)
    else:
      pick_top_solution=True
      if rho_stdev == 0.0:
        centroids = [flex.first_index(delta,flex.max(delta))]
      elif delta_stdev == 0.0:
        centroids = [flex.first_index(rho,flex.max(rho))]

    significant_delta = []
    significant_rho = []
    debug_fix_clustering = True
    if debug_fix_clustering:
      if not pick_top_solution:
        delta_z_cutoff = min(1.0, max(delta_z))
        rho_z_cutoff = min(1.0, max(rho_z))
        for ic in range(NN):
          # test the density & rho
          if delta_z[ic] >= delta_z_cutoff:
            significant_delta.append(ic)
          if rho_z[ic] >= rho_z_cutoff:
            significant_rho.append(ic)
        centroid_candidates = list(set(significant_delta).intersection(set(significant_rho)))
        # Now compare the relative orders of the max delta_z and max rho_z to make sure they are within 1 stdev
        centroids = []
        max_delta_z_candidates = -999.9
        max_rho_z_candidates = -999.9
        for ic in centroid_candidates:
          if delta_z[ic] > max_delta_z_candidates:
            max_delta_z_candidates = delta_z[ic]
          if rho_z[ic] > max_rho_z_candidates:
            max_rho_z_candidates = rho_z[ic]
        for ic in centroid_candidates:
          if max_delta_z_candidates - delta_z[ic] < 1.0 and max_rho_z_candidates - rho_z[ic] < 1.0:
            centroids.append(ic)

      item_idxs = [delta_order[ic] for ic,centroid in enumerate(centroids)]
      for item_idx in item_idxs:
        cluster_id[item_idx] = n_cluster
        print ('CLUSTERING_STATS',item_idx,cluster_id[item_idx] )
        n_cluster +=1
        ####
    else:
      for ic in range(NN):
        item_idx = delta_order[ic]
        if ic != 0:
          if delta[item_idx] <= 0.25*delta[delta_order[0]]: # too low to be a medoid
            continue
        item_rho_order = rho_order_list.index(item_idx)
        if (item_rho_order)/NN < MAX_PERCENTILE_RHO:
          cluster_id[item_idx] = n_cluster
          print ('CLUSTERING_STATS',ic,item_idx,item_rho_order,cluster_id[item_idx])
          n_cluster +=1
    ###
#
#
    print ('Found %d clusters'%n_cluster)
    for x in range(NN):
      if cluster_id[x] >= 0:
        print ("XC", x,cluster_id[x], rho[x], delta[x])
    self.cluster_id_maxima = cluster_id.deep_copy()
    R.cluster_assignment(rho_order, cluster_id)
    self.cluster_id_full = cluster_id.deep_copy()

    #halo = flex.bool(NN,False)
    #border = R.get_border( cluster_id = cluster_id )

    #for ic in range(n_cluster): #loop thru all border regions; find highest density
    #  this_border = (cluster_id == ic) & (border==True)
    #  if this_border.count(True)>0:
    #    highest_density = flex.max(rho.select(this_border))
    #    halo_selection = (rho < highest_density) & (this_border==True)
    #    if halo_selection.count(True)>0:
    #      cluster_id.set_selected(halo_selection,-1)
    #    core_selection = (cluster_id == ic) & ~halo_selection
    #    highest_density = flex.max(rho.select(core_selection))
    #    too_sparse = core_selection & (rho.as_double() < highest_density/10.) # another heuristic
    #    if too_sparse.count(True)>0:
    #      cluster_id.set_selected(too_sparse,-1)
    self.cluster_id_final = cluster_id.deep_copy()

def get_uc_consensus(experiments_list, show_plot=False, return_only_first_indexed_model=False,finalize_method=None, clustering_params=None):
  '''
  Uses the Rodriguez Laio 2014 method to do a clustering of the unit cells and then vote for the highest
  consensus unit cell. Input needs to be a list of experiments object.
  Clustering code taken from github.com/cctbx-xfel/cluster_regression
  Returns an experiment object with crystal unit cell from the cluster with the most points
  '''
  if return_only_first_indexed_model:
    return [experiments_list[0].crystals()[0]], None
  cells = []
  from xfel.clustering.singleframe import CellOnlyFrame
  save_plot = False
  # Flag for testing Lysozyme data from NKS.Make sure cluster_regression repository is present and configured
  # Program will exit after plots are displayed if this flag is true
  test_nks = False
  if test_nks:
    from cctbx import crystal
    import libtbx.load_env
    cluster_regression = libtbx.env.find_in_repositories(
        relative_path="cluster_regression",
        test=os.path.isdir)
    file_name = os.path.join(cluster_regression, 'examples', 'lysozyme1341.txt')
    for line in open(file_name, "r").xreadlines():
      tokens = line.strip().split()
      unit_cell = tuple(float(x) for x in tokens[0:6])
      space_group_symbol = tokens[6]
      crystal_symmetry = crystal.symmetry(unit_cell = unit_cell, space_group_symbol = space_group_symbol)
      cells.append(CellOnlyFrame(crystal_symmetry))
  else:
    for experiment in experiments_list:
      if len(experiment.crystals()) >1: print ('IOTA:Should have only one crystal model')
      crystal_symmetry = experiment.crystals()[0].get_crystal_symmetry()
      cells.append(CellOnlyFrame(crystal_symmetry))
  MM = [c.mm for c in cells] # metrical matrices
  MM_double = flex.double()
  for i in range(len(MM)):
    Tup = MM[i]
    for j in range(6):
      MM_double.append(Tup[j])
  print('There are %d cells'%len(MM))
  coord_x = flex.double([c.uc[0] for c in cells])
  coord_y = flex.double([c.uc[1] for c in cells])
  if show_plot or save_plot:
    import matplotlib
    if not show_plot:
      matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    #from IPython import embed; embed(); exit()
    plt.plot([c.uc[0] for c in cells],[c.uc[1] for c in cells],"k.", markersize=3.)
    plt.axes().set_aspect("equal")
  if save_plot:
    plot_name = 'uc_cluster.png'
    plt.savefig(plot_name,
                size_inches=(10,10),
                dpi=300,
                bbox_inches='tight')
  if show_plot:
    plt.show()
  print ('Now constructing a Dij matrix: Starting Unit Cell clustering')
  NN = len(MM)
  from cctbx.uctbx.determine_unit_cell import NCDist_flatten
  Dij = NCDist_flatten(MM_double)
  d_c = flex.mean_and_variance(Dij.as_1d()).unweighted_sample_standard_deviation()#6.13
  #FIXME should be a PHIL param
  if len(cells) < 5:
    return [experiments_list[0].crystals()[0]], None
  CM = clustering_manager(Dij=Dij, d_c=d_c, max_percentile_rho=0.95)
  n_cluster = 1+flex.max(CM.cluster_id_final)
  print (len(cells), ' datapoints have been analyzed')
  print ('%d CLUSTERS'%n_cluster)
  for i in range(n_cluster):
    item = flex.first_index(CM.cluster_id_maxima, i)
    print ('Cluster %d central Unit cell = %d'%(i, item))
    cells[item].crystal_symmetry.show_summary()

  # More plots for debugging
  appcolors = ['b', 'r', '#ff7f0e', '#2ca02c',
              '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
              '#bcbd22', '#17becf']
  if show_plot:
    # Decision graph
    import matplotlib.pyplot as plt
    plt.plot(CM.rho, CM.delta, "r.", markersize=3.)
    for x in range(NN):
      if CM.cluster_id_maxima[x] >=0:
        plt.plot([CM.rho[x]], [CM.delta[x]], "ro")
    plt.show()

  if show_plot:
    import matplotlib.pyplot as plt
    colors = [appcolors[i%10] for i in CM.cluster_id_full]
    plt.scatter(coord_x, coord_y, marker='o', color=colors, linewidth=0.4, edgecolor='k')
    for i in range(n_cluster):
      item = flex.first_index(CM.cluster_id_maxima, i)
      plt.plot([cells[item].uc[0]], cells[item].uc[1], 'y.')
      plt.axes().set_aspect("equal")
      plt.show()
  if test_nks:
    exit()

  # Now look at each unit cell cluster for orientational clustering
  # idea is to cluster the orientational component in each of the unit cell clusters
  #
  do_orientational_clustering = not return_only_first_indexed_model # temporary.
  dxtbx_crystal_models = []
  if do_orientational_clustering:
    print ('IOTA: Starting orientational clustering')
    Dij_ori = {} # dictionary to store Dij for each cluster
    uc_experiments_list = {} # dictionary to store experiments_lists for each cluster
    from collections import Counter
    uc_cluster_count = Counter(list(CM.cluster_id_final))
    # instantiate the Dij_ori flat 1-d array
    # Put all experiments list from same uc cluster together
    if True:
      from scitbx.matrix import sqr
      from cctbx_orientation_ext import crystal_orientation
      #crystal_orientation_list = []
      #for i in range(len(experiments_list)):
      #  crystal_orientation_list.append(crystal_orientation(experiments_list[i].crystals()[0].get_A(), True))
        #from IPython import embed; embed(); exit()
        #A_direct = sqr(crystal_orientation_list[i].reciprocal_matrix()).transpose().inverse()
        #print ("Direct A matrix 1st element = %12.6f"%A_direct[0])
    for i in range(len(experiments_list)):
      if CM.cluster_id_full[i] not in uc_experiments_list:
        uc_experiments_list[CM.cluster_id_full[i]] = []
      uc_experiments_list[CM.cluster_id_full[i]].append(experiments_list[i])
    for cluster in uc_cluster_count:
      # Make sure there are atleast a minimum number of samples in the cluster
      if uc_cluster_count[cluster] < 5:
        continue
      Dij_ori[cluster] = flex.double([[0.0]*uc_cluster_count[cluster]]*uc_cluster_count[cluster])
    # Now populate the Dij_ori array
      N_samples_in_cluster = len(uc_experiments_list[cluster])
      for i in range(N_samples_in_cluster-1):
        for j in range(i+1, N_samples_in_cluster):
          dij_ori = get_dij_ori(uc_experiments_list[cluster][i].crystals()[0],uc_experiments_list[cluster][j].crystals()[0])
          Dij_ori[cluster][N_samples_in_cluster*i+j] = dij_ori
          Dij_ori[cluster][N_samples_in_cluster*j+i] = dij_ori

    # Now do the orientational cluster analysis
    #from IPython import embed; embed(); exit()
    d_c_ori = 0.13
    from exafel_project.ADSE13_25.clustering.plot_with_dimensional_embedding import plot_with_dimensional_embedding
    #plot_with_dimensional_embedding(1-Dij_ori[1]/flex.max(Dij_ori[1]), show_plot=True)
    for cluster in Dij_ori:
      d_c_ori=flex.mean_and_variance(Dij_ori[cluster].as_1d()).unweighted_sample_standard_deviation()
      CM_ori = clustering_manager(Dij=Dij_ori[cluster], d_c=d_c_ori, max_percentile_rho=0.85)
      n_cluster_ori = 1+flex.max(CM_ori.cluster_id_final)
      #from IPython import embed; embed()
      #FIXME should be a PHIL param
      for i in range(n_cluster_ori):
        if len([zz for zz in CM_ori.cluster_id_final if zz == i]) < 5:
          continue
        item = flex.first_index(CM_ori.cluster_id_maxima, i)
        dxtbx_crystal_model = uc_experiments_list[cluster][item].crystals()[0]
        dxtbx_crystal_models.append(dxtbx_crystal_model)
        from scitbx.matrix import sqr
        from cctbx_orientation_ext import crystal_orientation
        crystal_orientation = crystal_orientation(dxtbx_crystal_model.get_A(), True)
        A_direct = sqr(crystal_orientation.reciprocal_matrix()).transpose().inverse()
        print ("IOTA: Direct A matrix 1st element of orientational cluster %d  = %12.6f"%(i,A_direct[0]))
      if show_plot:
        # Decision graph
        stretch_plot_factor = 1.05 # (1+fraction of limits by which xlim,ylim should be set)
        import matplotlib.pyplot as plt
        plt.plot(CM_ori.rho, CM_ori.delta, "r.", markersize=3.)
        for x in range(len(list(CM_ori.cluster_id_final))):
          if CM_ori.cluster_id_maxima[x] >=0:
            plt.plot([CM_ori.rho[x]], [CM_ori.delta[x]], "ro")
        #from IPython import embed; embed(); exit()
        plt.xlim([-10,stretch_plot_factor*flex.max(CM_ori.rho)])
        plt.ylim([-10,stretch_plot_factor*flex.max(CM_ori.delta)])
        plt.show()
  # Make sure the crystal models are not too close to each other
  # FIXME should be a PHIL
  min_angle = 5.0 # taken from indexer.py
  close_models_list = []
  if len(dxtbx_crystal_models) > 1:
    from dials.algorithms.indexing.compare_orientation_matrices import difference_rotation_matrix_axis_angle
    for i_a in range(0,len(dxtbx_crystal_models)-1):
      for i_b in range(i_a,len(dxtbx_crystal_models)):
        cryst_a = dxtbx_crystal_models[i_a]
        cryst_b = dxtbx_crystal_models[i_b]
        R_ab, axis, angle, cb_op_ab = difference_rotation_matrix_axis_angle(cryst_a, cryst_b)
      # FIXME
        if abs(angle) < min_angle: # degrees
          close_models_list.append((i_a, i_b))

  # Now prune the dxtbx_crystal_models list
  for close_models in close_models_list:
    i_a,i_b = close_models
    if dxtbx_crystal_models[i_a] is not None and dxtbx_crystal_models[i_b] is not None:
      dxtbx_crystal_models[i_a] = None

  dxtbx_crystal_models=[x for x in dxtbx_crystal_models if x is not None]
  if len(dxtbx_crystal_models) > 0:
    return dxtbx_crystal_models, None
  else:
    # If nothing works, atleast return the 1st crystal model that was found
    return [experiments_list[0].crystals()[0]], None
