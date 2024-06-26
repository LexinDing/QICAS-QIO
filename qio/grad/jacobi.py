import numpy as np
import copy
import sys
from scipy.linalg import expm

import logging

from qio.entropy import shannon, get_cost_fqi

np.set_printoptions(threshold=sys.maxsize)

logger = logging.getLogger('qio')


def jacobi_cost(theta,i,j,rdm1,rdm2,inactive_indices):

    '''
    Sum of orbital entropy of the two orbitals i and j under one single jacobi rotation with angle t

    Args:
        theta (float): rotational angle
        i,j (int): orbital indices
        gamma (ndarray): current 1RDM
        Gamma (ndarray): current 2RDM
        inactive_indices (list): indices of inactive orbitals

    Returns:
        cost_fun (float): S(rho_i) + S(rho_j)

    '''

    
    
    cost_fun = 0
    # two orbital rotation
    u1 = np.array([[np.cos(theta),np.sin(theta)],[-np.sin(theta),np.cos(theta)]])
        
    indices = [i,j]

    for k in indices:
        if k in inactive_indices:
            index = 1*(k==j)
            nu = 0.
            nd = 0.
            nn = 0.
            
            for m in range(2):
                for n in range(2):
                    nu += u1[index,m]*u1[index,n]*rdm1[2*indices[m],2*indices[n]]     
                    nd += u1[index,m]*u1[index,n]*rdm1[2*indices[m]+1,2*indices[n]+1]
                    for p in range(2):
                        for q in range(2):
                            nn += u1[index,m]*u1[index,n]*u1[index,p]*u1[index,q]*rdm2[indices[m],indices[n],indices[p],indices[q]]
        
            # compute orbital entropy
            spec = np.array([1-nu-nd+nn,nu-nn,nd-nn,nn])
            cost_fun += shannon(spec)
            

    return cost_fun


def jacobi_transform(gamma,Gamma,i,j,t):

    '''
    Perform two-orbital rotation to 1- and 2RDM between orbital i and j by angle t

    Args:
        gamma (ndarray): current 1RDM
        Gamma (ndarray): current 2RDM
        i,j (int): orbital indices
        t (float): rotational angle

    Returns:
        gamma_ (ndarray): transformed 1RDM
        Gamma_ (ndarray): transformed 2RDM
    '''

    no = len(Gamma)
    u1 = np.array([[np.cos(t),np.sin(t)],[-np.sin(t),np.cos(t)]])
    U1 = np.eye(no)
    U1[i,i] = u1[0,0]
    U1[i,j] = u1[0,1]
    U1[j,i] = u1[1,0]
    U1[j,j] = u1[1,1]
    #print(U1)
    gamma_ = np.zeros((2*no,2*no))
    Gamma_ = np.zeros((no,no,no,no))

    Gamma_ = np.einsum('ia,jb,kc,ld,abcd->ijkl',U1,U1,U1,U1,Gamma,optimize='optimal')
        
    for a in range(no):
        testa = 0
        if a == i or a == j:
            m_list = list(set([a,i,j]))
            testa = 1
        else:
            m_list = [a]
        for b in range(no):
            testb = 0
            if b == i or b == j:
                n_list = list(set([b,i,j]))
                testb = 1
            else:
                n_list = [b]
            if testa + testb > 0:
                for m in m_list:
                    for n in n_list:
                        gamma_[2*a,2*b] += U1[a,m]*U1[b,n]*gamma[2*m,2*n]
                        gamma_[2*a+1,2*b+1] += U1[a,m]*U1[b,n]*gamma[2*m+1,2*n+1]
            else:
                gamma_[2*a,2*b] = gamma[2*a,2*b]
                gamma_[2*a+1,2*b+1] = gamma[2*a+1,2*b+1]
                    
    return gamma_, Gamma_

def jacobi_direct(i,j,gamma,Gamma,inactive_indices):
    
    '''

    Optimize a single two-orbital rotation to minimize the sum of entropy of orbital i and j

    Args:
        i,j (int): orbital indices
        gamma (ndarray): current 1RDM
        Gamma (ndarray): current 2RDM
        inactive_indices (list): indices of inactive orbitals

    Returns:
        None: if no rotation between orbital i and j can lower the entropy
        t_opt_new: optimal rotational angle between orbital i and j

    '''

    cost = jacobi_cost(0,i,j,gamma,Gamma,inactive_indices)
    test = 0
    grid = 0.01
    t_opt = 0
    for t in np.arange(grid, np.pi, grid):
        new_cost = jacobi_cost(t,i,j,gamma,Gamma,inactive_indices)
        if cost > new_cost:
            #test = 1
            t_opt = t
            cost = new_cost
    small_grid = 0.0001
    if t_opt == 0:
        t_opt += grid
    
    for t in np.arange(t_opt-grid,t_opt+grid,small_grid):
        new_cost = jacobi_cost(t,i,j,gamma,Gamma,inactive_indices)
        if cost > new_cost + 1e-8:
            test = 1
            t_opt_new = t
            cost = new_cost
    if test == 1:
        return t_opt_new
    else:
        return None


def minimize_orb_corr_jacobi(gamma,Gamma,inactive_indices,max_cycle):
    
    '''

    Orbital optimization from initial orbitals to QICAS optimized orbitals

    Args:
        gamma (ndarray): initial 1RDM
        Gamma (ndarray): initial 2RDM
        inactive_indices (list): inactive orbital indices
        max_cycle (int): maximal number of cycles of jacobi rotation during orbital optimization

    Returns:
        rotations (list): history of jacobi rotations (orbital_i, orbital_j, rotational_angle)
        U (ndarray): unitary that transform the initial orbitals to the QICAS-optimized orbitals
        gamma (ndarray): transformed 1RDM
        Gamma (ndarray): transformed 2RDM

    '''



    no = len(Gamma) 
    gamma0 = copy.deepcopy(gamma) # get_1_pt_rdm_molpro(state,no)
    Gamma0 = copy.deepcopy(Gamma) # get_rel_2_pt_rdm_molpro(state,no)
    

    def jacobi_step(t,i,j):
        V = np.eye(no)
        V[i,i] = np.cos(t)
        V[i,j] = np.sin(t)
        V[j,i] = -np.sin(t)
        V[j,j] = np.cos(t)
        return V

    # Initialize a small rotation
    X = (np.random.rand(no,no)/2-1)/1/(1+49*np.random.rand())
    X = X - X.T
    U = expm(X)
    U_ = np.kron(U,np.eye(2))
    gamma0 = np.einsum('ia,jb,ab->ij',U_,U_,gamma0,optimize='optimal')
    Gamma0 = np.einsum('ia,jb,kc,ld,abcd->ijkl',U,U,U,U,Gamma0,optimize='optimal')


    rotations = []

    logger.info('Optimizig Orbitals...')
    cost = 100
    new_cost = 100
    cycle_cost = 100
    for n in range(max_cycle):
        logger.info('============== Cycle '+str(n+1)+' ==============')
        orb_list = np.arange(0,no)
        np.random.shuffle(orb_list)
        for a in range(no):
            i = orb_list[a]
            for b in range(a):
                j = orb_list[b]
                if (i in inactive_indices) or (j in inactive_indices):
                    
                    t = jacobi_direct(i,j,gamma0,Gamma0,inactive_indices)
                    
                    if t != None:
                        #print('t=',t)
                        gamma0, Gamma0 = jacobi_transform(gamma0,Gamma0,i,j,t)
                        new_cost = get_cost_fqi(gamma0,Gamma0,inactive_indices)
                        #print(i,j,'cost =',new_cost)
                        advance = cost - new_cost
                        cost = new_cost
                        U = np.matmul(jacobi_step(t,i,j),U)
                        rotations.append([i+1,j+1,t/np.pi*180])
                        #print(gamma0)
                    
        
        tol = 1e-7
        if cycle_cost - new_cost < tol:
            logger.info('reached tol =',tol)
            break
        cycle_cost = new_cost
        logger.info('cost=',cycle_cost)

    return rotations, U, gamma0, Gamma0

def reorder_fast(gamma, Gamma, n_cas, n_core):
    """
    Reorder the orbitals after QICAS optimization. 
    1. Sort all orbitals wrt to their entropy
    2. Sort the inactive orbitals wrt to their occupation numbers
    3. Sort the active orbitals wrt to their occupation numbers
    4. Move the first N_core orbitals to the front

    Args:
        gamma (ndarray): 1RDM
        Gamma (ndarray): 2RDM
        n_cas (int): number of active orbitals
        n_core (int): number of core orbitals

    Returns:
        P (ndarray): permutation matrix that performs the desired reordering
    """
    n_orb = len(Gamma) 
    i = np.arange(n_orb, dtype=int)
    nu = gamma[2*i,2*i]
    nd = gamma[2*i+1,2*i+1]
    nn = Gamma[i,i,i,i]
    occ_num = nu + nd
    spec = np.array([1-nu-nd+nn, nu-nn, nd-nn, nn])
    s_val = -np.sum(np.log(spec)*spec, axis=0)
    s_val_init = s_val.copy()
    inds = np.argsort(s_val)[::-1]
    # get the permutation matrix for the above sorting
    P = np.eye(n_orb)[inds]
    s_val = s_val[inds]
    occ_num = occ_num[inds]

    # sort the inactive orbitals wrt to occupation numbers
    inds_inactive = np.argsort(occ_num[n_cas:])[::-1]
    # get the permutation matrix for the above sorting
    inds = np.concatenate((np.arange(n_cas, dtype=int), (n_cas+inds_inactive)))
    P = P[inds]
    s_val = s_val[inds]
    occ_num = occ_num[inds]

    # sort the active orbitals wrt to occupation numbers
    inds_active = np.argsort(occ_num[:n_cas])[::-1]
    # get the permutation matrix for the above sorting
    inds = np.concatenate((inds_active, np.arange(n_cas, n_orb, dtype=int)))

    s_val = s_val[inds]
    occ_num = occ_num[inds]
    P = P[inds]

    # move the first N_core orbitals to the front
    inds =  [i for i in range(n_cas, n_cas+n_core)]+[i for i in range(n_cas)] + [i for i in range(n_cas+n_core, n_orb)]
    P = P[inds]
    s_val = s_val[inds]
    occ_num = occ_num[inds]
    logger.info("Orbital entropies =", str(s_val))
    logger.info("Orbital occupation numbers =", str(occ_num))
    if occ_num[n_core+n_cas-1] < occ_num[n_core+n_cas]:
        logger.info("Warning: the orbitals are not ordered correctly wrt to occupation numbers!")
    assert np.allclose(P @ s_val_init, s_val)

    return P


def reorder_occ(gamma, Gamma):
    """
    Reorders orbitals occording to their occupation numbers
    """
    n_orb = len(Gamma) 
    i = np.arange(n_orb, dtype=int)
    nu = gamma[2*i,2*i]
    nd = gamma[2*i+1,2*i+1]
    nn = Gamma[i,i,i,i]
    occ_num = nu + nd
    spec = np.array([1-nu-nd+nn, nu-nn, nd-nn, nn])
    s_val = -np.sum(np.log(spec)*spec, axis=0)
    inds = np.argsort(occ_num)[::-1]
    P = np.eye(n_orb)[inds]
    s_val = s_val[inds]
    occ_num = occ_num[inds]
    
    logger.info("Orbital entropies =")
    logger.info(s_val)
    logger.info("Orbital occupation numbers =")
    logger.info(str(occ_num))

    return P, s_val, occ_num


    


def reorder(gamma,Gamma,N_cas):

    '''
    After orbital rotations, among the inactive orbitals move the orbitals more than 
    halfly occupied to closed (front of list) and the ones less than halfly occupied 
    to virtual (back of list)

    Args:
        gamma (ndarray): initial 1RDM
        Gamma (ndarray): initial 2RDM
        N_cas (int): number of active orbitals

    Returns:
        rotations (list): sequence of used rotations
        n_closed (int): number of closed orbitals predicted by QICAS
        V (ndarray): permutation matrix that performs the desired reordering 

    '''

    test = 1
    #S1 = orb_corr(gamma,Gamma)
    S1 = np.zeros(len(Gamma))
    N1 = np.zeros(len(Gamma))
    for i in range(len(Gamma)):
        nu = gamma[2*i,2*i]
        nd = gamma[2*i+1,2*i+1]
        N1[i] = nu + nd
        spec = [1-nu,nu,1-nd,nd]
        S1[i] = shannon(spec)
    #print(S1,N1)
    rotations = []
    no = len(S1)
    V = np.eye(no)
    
    while test == 1:
        test = 0
        for i in range(len(S1)-1):
            if S1[i] < S1[i+1]:
                test = 1

                c = S1[i]
                S1[i] = S1[i+1]
                S1[i+1] = c


                c = N1[i]
                N1[i] = N1[i+1]
                N1[i+1] = c

                rotations = rotations + [[i+1,i+2,0]]
                V_ = np.eye(no)
                V_[i,i] = 0
                V_[i+1,i+1] = 0
                V_[i,i+1] = 1
                V_[i+1,i] = 1
                V = np.matmul(V_,V)
    
    
    n_closed = 0
    for j in range(N_cas,len(S1)):
        if N1[j] > 1:
            n_closed += 1
            for i in range(j):
                #print(i)

                c = S1[j-1-i]
                S1[j-1-i] = S1[j-i]
                S1[j-i] = c


                c = N1[j-1-i]
                N1[j-1-i] = N1[j-i]
                N1[j-i] = c

                rotations = rotations + [[j-i,j-i+1,0]]
                V_ = np.eye(no)
                V_[j-1-i,j-1-i] = 0
                V_[j-i,j-i] = 0
                V_[j-1-i,j-i] = 1
                V_[j-i,j-1-i] = 1
                V = np.matmul(V_,V)


    logger.info(S1,N1)
    logger.info('n_closed =',n_closed)
    return rotations, n_closed, V


