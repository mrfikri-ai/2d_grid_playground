from dynamics import QuadDynamics
from controller import *
import numpy as np
import matplotlib.pyplot as plt
from cvxopt import matrix
from cvxopt import solvers

from simulator import Map, LidarSimulator, Robot
import math
import random

a = 1
b = 1
safety_dist = 2 # TODO: change

class ECBF_control():
    def __init__(self, state, goal=np.array([[10], [0]]), laser_angle=np.radians([0,0])):
        self.state = state
        self.shape_dict = {}
        Kp = 3
        Kd = 4
        self.K = np.array([Kp, Kd])
        self.goal=goal
        self.laser_angle = laser_angle
        self.num_h = self.laser_angle.shape[0]
        self.use_safe = True
        # noise terms
        self.noise_x = np.zeros((3,))

    def add_state_noise(self, variance):
        # Apply random walk noise
        self.noise_x += (np.random.rand(3) - 0.5) * variance
        self.state["x"] += self.noise_x  # position
        # TODO: do for velocity too?

    def compute_h_hd(self, laser_range=None):
        h = self.compute_h(laser_range=laser_range)
        hd = self.compute_hd()
        # print("h shape", h.shape)
        # print("hd shape", hd.shape)
        return np.hstack((h, hd)).astype(np.double)

    def compute_h(self, obs=None,laser_range=None):
        # return self.compute_h_superellip(obs)
        # print("Comptue_h", laser_range)
        return self.compute_h_box(laser_range)

    def compute_hd(self, obs=None):
        # return self.compute_hd_superellip(obs)
        return self.compute_hd_box()

    def compute_A(self,obs=None):
        # return self.compute_A_superellip(obs)
        return self.compute_A_box()

    def compute_b(self,obs=None, laser_range=None):
        # return self.compute_b_ellip(obs)
        return self.compute_b_box(laser_range)

    def compute_safe_control(self,obs, laser_range):
        if self.use_safe:
            A = self.compute_A(obs)
            assert(A.shape == (self.num_h,2))
            b_ineq = self.compute_b(obs, laser_range)

            #Make CVXOPT quadratic programming problem
            P = matrix(np.eye(2), tc='d')
            q = -1 * matrix(self.compute_nom_control(), tc='d')
            G = -1 * matrix(A.astype(np.double), tc='d')

            h = -1 * matrix(b_ineq.astype(np.double), tc='d')
            solvers.options['show_progress'] = False
            sol = solvers.qp(P,q,G, h, verbose=False) # get dictionary for solution


            optimized_u = sol['x']

        else:
            optimized_u = self.compute_nom_control()


        return optimized_u

    def compute_nom_control(self, Kn=np.array([-0.08, -0.2])):
        #! mock
        vd = Kn[0]*(np.atleast_2d(self.state["x"][:2]).T - self.goal)
        u_nom = Kn[1]*(np.atleast_2d(self.state["xdot"][:2]).T - vd)

        if np.linalg.norm(u_nom) > 1:
            u_nom = (u_nom/np.linalg.norm(u_nom))

        # u_nom = np.array([0.02, 0.005])
        return u_nom.astype(np.double)

    # Box-specific functions
    def compute_h_box(self, laser_range):
        print("comp_h_box", laser_range)
        hr = h_func(self.state["x"][0], self.state["x"][1], a, b, safety_dist, self.laser_angle, laser_range)
        assert(hr.shape==(self.num_h,1))
        return hr
    
    def compute_hd_box(self):
        # TODO: confirm sign
        h = np.empty((0,1))
        for i in range(self.num_h):
            h = np.vstack((h, -np.sin(self.laser_angle[i])*self.state["xdot"][0] - np.cos(self.laser_angle[i])*self.state["xdot"][1]))
        return h
        # hd1 = -self.state["xdot"][1]
        # hd2 = -self.state["xdot"][0]

        # hd = np.vstack((hd1, hd2))
        assert(hd.shape==(self.num_h,1))
        return hd

    def compute_A_box(self):
        A = np.empty((0,2))
        for i in range(self.num_h):
            A = np.vstack((A, np.array([-np.sin(self.laser_angle[i]), -np.cos(self.laser_angle[i])])))
        # A = np.array([[0, -1], [-1, 0]])
        assert(A.shape==(self.num_h,2))
        # A2 = np.array()
        return A

    def compute_b_box(self, laser_range=None):
        # print("K", self.K.shape)
        # print("hhd", self.compute_h_hd().shape)
        b_ineq = - self.compute_h_hd(laser_range) @ np.atleast_2d(self.K).T
        # print(b_ineq.shape)
        assert(b_ineq.shape==(self.num_h,1))
        return b_ineq     

    # # Superellipsoid-specific functions
    # def compute_h_superellip(self, obs):
    #     rel_r = np.atleast_2d(self.state["x"][:2]).T - obs
    #     # TODO: a, safety_dist, obs, b
    #     hr = h_func(rel_r[0], rel_r[1], a, b, safety_dist)
    #     return hr

    # def compute_hd_superellip(self, obs):
    #     rel_r = np.atleast_2d(self.state["x"][:2]).T - obs
    #     rd = np.atleast_2d(self.state["xdot"][:2]).T
    #     term1 = (4 * np.power(rel_r[0],3) * rd[0])/(np.power(a,4))
    #     term2 = (4 * np.power(rel_r[1],3) * rd[1])/(np.power(b,4))
    #     return term1+term2

    # def compute_A_superellip(self, obs):
    #     rel_r = np.atleast_2d(self.state["x"][:2]).T - obs
    #     A0 = (4 * np.power(rel_r[0], 3))/(np.power(a, 4))
    #     A1 = (4 * np.power(rel_r[1], 3))/(np.power(b, 4))

    #     return np.array([np.hstack((A0, A1))])


    # def compute_b_ellip(self, obs):
    #     """extra + K * [h hd]"""
    #     rel_r = np.atleast_2d(self.state["x"][:2]).T - obs
    #     rd = np.array(np.array(self.state["xdot"])[:2])
    #     extra = -(
    #         (12 * np.square(rel_r[0]) * np.square(rd[0]))/np.power(a,4) +
    #         (12 * np.square(rel_r[1]) * np.square(rd[1]))/np.power(b, 4)
    #     )

    #     b_ineq = extra - self.K @ self.compute_h_hd(obs)
    #     return b_ineq



@np.vectorize
def h_func_superellip(r1, r2, a, b, safety_dist):
    hr = np.power(r1,4)/np.power(a, 4) + \
        np.power(r2, 4)/np.power(b, 4) - safety_dist
    return hr

def h_func_box(r1, r2, a, b, safety_dist, laser_angle, laser_range):
    # print("hf", laser_angle)
    num_h = laser_angle.shape[0]
    r_max = 10
    if r1.shape == ():
        h = np.zeros((num_h, 1))
        
        for i in range(num_h):
            li = laser_angle[i]
            
            # if laser_range is None:
            #     ri = 30 #! max_range
            #     print("no laser range")
            # else:
            ri = laser_range[i]
            # print(ri)
            h_i = ri - safety_dist #-np.sin(li)*r1 - np.cos(li)*r2 + r_max - safety_dist
            # h_i = -np.sin(li)*r1 - np.cos(li)*r2 + r_max - safety_dist
            # h_i = np.sin(laser_angle[i])*(r_max-r1) + np.cos(laser_angle[i]) * (r_max-r2) - safety_dist
            # print(np.cos(laser_angle) * (r_max-r2) )
            h[i] = h_i 
    else:
        h = np.empty((0,200))
        for i in range(num_h):
            li = laser_angle[i]
            h = np.vstack((h, -np.sin(li)*r1 - np.cos(li)*r2 + r_max -safety_dist))
    return h

def h_func(r1, r2, a, b, safety_dist, laser_angle, laser_range):
    
    return h_func_box(r1, r2, a, b, safety_dist, laser_angle, laser_range)

def plot_h(obs, laser_angle, h_func=h_func_box):

    plot_x = np.arange(-10, 10, 0.1)
    plot_y = np.arange(-10, 10, 0.1)
    xx, yy = np.meshgrid(plot_x, plot_y, sparse=True)
    z = h_func_box(xx, yy, a, b, safety_dist, laser_angle) 
    z = np.reshape(z, (laser_angle.shape[0],200, 200))
    z = z > 0
    z = np.all(z,axis=0)
    h = plt.contourf(plot_x, plot_y, z, [-1, 0, 1], colors=["black","white"], alpha=0.25)
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.pause(0.00000001)

def run_trial(state, obs_loc,goal, num_it, variance):
    """ Run 1 trial"""
    # Initialize necessary classes
    print("start!!")

    # load map
    src_path_map = "data/two_obs.dat"
    map1 = Map(src_path_map)

    # initialize robot (initializes lidar with map) 
    robbie = Robot(map1)
    robbie.update(state)
    dyn = QuadDynamics()
    laser_angle = np.radians(np.arange(6)*60) 
    ecbf = ECBF_control(state=state,goal=goal, laser_angle=laser_angle)
    state_hist = []
    new_obs = np.atleast_2d(obs_loc).T
    h_hist = np.zeros((num_it))
    

    # Loop through iterations
    for tt in range(num_it):
        # print("Roobie", robbie.lidar.ranges)
        # Get ECBF Control
        u_hat_acc = ecbf.compute_safe_control(obs=new_obs, laser_range=robbie.lidar.ranges)
        u_hat_acc = np.ndarray.flatten(
            np.array(np.vstack((u_hat_acc, np.zeros((1, 1))))))  # acceleration
        assert(u_hat_acc.shape == (3,))
        u_motor = go_to_acceleration(
            state, u_hat_acc, dyn.param_dict)  # desired motor rate ^2

        # Step Dynamics and update state
        state = dyn.step_dynamics(state, u_motor)
        ecbf.state = state
        state_hist.append(state["x"]) # append true state
        # print(tt)
        robbie.update(state)
        # print("ranges",robbie.lidar.ranges)
        if(tt % 20 == 0):
            print("Time " + str(tt))
            plt.cla()
            
            
            map1.visualize_map()
            nom_cont = ecbf.compute_nom_control()
            robbie.visualize(nom_cont, u_hat_acc[:2])
            plt.pause(0.1)
        
            # print(tt)
            # plt.cla()
            # state_hist_plot = np.array(state_hist)
            # nom_cont = ecbf.compute_nom_control()
            # plt.plot([state_hist_plot[-1, 0], state_hist_plot[-1, 0] + 100 *
            #           u_hat_acc[0]],
            #          [state_hist_plot[-1, 1], state_hist_plot[-1, 1] + 100 * u_hat_acc[1]], label="Safe")
            # plt.plot([state_hist_plot[-1, 0], state_hist_plot[-1, 0] + 100 *
            #           nom_cont[0]],
            #          [state_hist_plot[-1, 1], state_hist_plot[-1, 1] + 100 * nom_cont[1]],label="Nominal")
            # plt.legend(["Safe", "Nominal"])
            # plt.plot(state_hist_plot[:, 0], state_hist_plot[:, 1],'b')
            # plt.plot(ecbf.goal[0], ecbf.goal[1], '*r')
            # plt.plot(state_hist_plot[-1, 0], state_hist_plot[-1, 1], '*b') # current
            # plt.xlim([-100, 100])
            # plt.ylim([-100, 100])
            # plot_h(new_obs, laser_angle)


    return np.array(state_hist), h_hist

def main():

    #! Experiment Variables
    num_it = 50000

    x_start_tr = 15 #! Mock, test near obstacle
    y_start_tr = 20
    goal_x = 70
    goal_y = 90
    goal = np.array([[goal_x], [goal_y]])
    state = {"x": np.array([x_start_tr, y_start_tr, 10]),
                "xdot": np.zeros(3,),
                "theta": np.radians(np.array([0, 0, 0])), 
                "thetadot": np.radians(np.array([0, 0, 0]))  
                }
    obs_loc = [0,0]

    state_hist, h_hist = run_trial(
        state, obs_loc, goal, num_it, variance=0)





if __name__=="__main__":
    main()
