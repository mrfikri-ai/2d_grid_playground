"""mrac_control.py
Model Reference Adaptive Control top-level file.
Run with `mrac_control.py`.

Author: Cherie Ho

Date: 9/16/2019

Based on Kannan and Johnson's `Model Reference Adaptive Control with a Constrained Linear Reference Model`

Includes:
* Reference Model
* Linear Compensator (PD)
* Adaptive Element
* Estimate Hedge
* Dynamic Inversion

"""
from dynamics import QuadDynamics, QuadHistory
from controller import go_to_position, pi_attitude_control
from visualize_dynamics import visualize_error_quadhist, visualize_quad_quadhist
from mrac_adapt import MRAC_Adapt
from sim_utils import *
import numpy as np
import matplotlib.pyplot as plt

class MRAC_control:
    def __init__(self, state, use_adapt=True):
        # Initialize adaptive element
        self.use_adapt = use_adapt
        self.ad_net = MRAC_Adapt()
        self.adapt_xin = None

        # Initialize states
        self.state = state
        self.x_c = None # external command. input to ref model
        self.x_r = np.hstack((self.state["x"], self.state["xdot"])) # states of reference model #TODO: check
        self.v_cr = np.zeros((3,))  # output of reference model
        self.v_h = np.zeros((3,))  # output of hedge
        self.v_ad = np.zeros((3,))  # Output of adaptive element
        self.v_lc = np.zeros((3,)) # Output of linear compensator
        self.v_tot = np.zeros((3,))
        self.model_track_error = np.zeros((6,)) # TODO: double check body frame
        self.cmd = None # Final output to actuator

        # Parameters
        self.lc_param = {"P": 3, "D": 1} # linear compensator gains #! handtuned
        self.Rp = np.diag(np.tile([self.lc_param["P"]], (3,))) #! hardcoded
        self.Rd = np.diag(np.tile([self.lc_param["D"]], (3,))) #! hardcoded
        # self.rm_param = {"P": 0.35, "D": 1} # reference model gains # ! handtuned
        self.rm_param = {"P": 3, "D": 1} # reference model gains # ! handtuned

        # Model state history
        self.m_x_hist = []
        self.m_xd_hist = []
        self.m_track_hist = []

        # Acceleration hist
        self.v_ad_hist = []
        self.v_lc_hist = []
        self.v_cr_hist = []

    def ref_model(self):
        """Linear reference model. Minimizes error
        between command and reference state.
        
        Allows one to impose prescribable limits on the evolution of the error states. Such as maximum speed and maximum acceleration.

        Parameters
        ----------
        self.x_r
            states of reference model
        self.x_c
            bounded external command signal
        self.v_h
            estimate hedge signal

        Updates
        -------
        self.v_cr
            for position control, acceleration from ref model
        """
        self.m_x_hist.append(np.copy(self.x_r[:3]))
        self.m_xd_hist.append(np.copy(self.x_r[3:]))
        model_error = self.x_c - self.x_r
        error_pos = model_error[0:3]  # command - reference
        des_vel = self.rm_param["P"] * error_pos
        self.v_cr = self.rm_param["D"] * (des_vel - self.x_r[3:])

    def update_model_state(self, dt):
        """Integrate reference states """
        acc_ref = self.v_cr - self.v_h # acceleration, TODO: check if subtract hedge?
        self.x_r[3:] = self.x_r[3:] + acc_ref * dt  # update vel_ref
        self.x_r[:3] = self.x_r[:3] + self.x_r[3:] * dt  # pos_ref
        # TODO: rotation?
        

    def linear_compensator(self):
        """Stabilizes linearized dynamics. PD control to minimize model tracking error.

        Parameters
        ----------
        self.model_track_err
            error between reference model and state

        Uses
        ----
        lc_param
            gains for linear compensator
        
        Returns
        -------
        v_lc
            output from linear compensator

        """

        # error_pos = self.model_track_error[0:3] # reference - state
        error_pos = self.x_r[0:3] - self.state["x"]
        des_vel = self.lc_param["P"] * error_pos
        self.v_lc = self.lc_param["D"] * (des_vel - self.state["xdot"])
        # print("self.v_lc", self.v_lc)
        # self.v_lc = self.lc_param["P"] * error_pos
        
        

    def dynamic_inversion(self, param_dict):
        """Invert dynamics. For outer loop, given v_tot, compute attitude.
        Similar to control allocator.

        TODO: do 1-1 mapping?
        Parameters
        ----------
        self.v_tot
            total v: v_cr + v_lc - v_ad

        state #TODO: use self.x
            state

        Returns
        -------
        desired_theta: np.ndarray(3,)
            desired roll, pitch, yaw angle (rad) to attitude controller

        """
        yaw = self.state["theta"][2]
        # tot_u_constant = 408750 * 4  # hover, for four motors
        # specific_force = tot_u_constant  / param_dict["m"] 

        # based on http://research.sabanciuniv.edu/33398/1/ICUAS2017_Final_ZAKI_UNEL_YILDIZ.pdf (Eq. 22-24)
        U1 = np.linalg.norm(self.v_tot - np.array([0, 0, param_dict["g"]]))
        des_pitch_noyaw =  np.arcsin(self.v_tot[0] / U1)
        des_angle = [des_pitch_noyaw,
                     np.arcsin(self.v_tot[1] / (U1 * np.cos(des_pitch_noyaw)))]
        des_pitch = des_angle[0] * np.cos(yaw) + des_angle[1] * np.sin(yaw)
        des_roll = des_angle[0] * np.sin(yaw) - des_angle[1] * np.cos(yaw)


        # TODO: move to attitude controller?
        des_pitch = np.clip(des_pitch, np.radians(-30), np.radians(30))
        des_roll = np.clip(des_roll, np.radians(-30), np.radians(30))

        # TODO: currently, set yaw as constant
        des_yaw = yaw
        des_theta = [des_roll, des_pitch, des_yaw]

        # vertical (acc_z -> thrust)
        # m = 0.5 #! mock, ask Basti if make sense
        thrust = (param_dict["m"] * (self.v_tot[2] - param_dict["g"])
                  )/param_dict["k"]  # T=ma/k
        max_tot_u = 400000000.0 # TODO: make in param_dict
        des_thrust_pc = thrust/max_tot_u

        
        return des_theta, des_thrust_pc

    def plant(self, des_theta, quad_dyn, des_thrust_pc):

        u = pi_attitude_control(self.state, des_theta, des_thrust_pc, quad_dyn.param_dict)
        self.state = quad_dyn.step_dynamics(self.state, u)
        # return state



    def adaptive_element(self):
        """
        Parameters
        ----------
        self.x
            robot state
        self.model_track_err
            model tracking error
        
        Update
        ------
        self.v_ad
            Adaptive element output

        """
        # get current body-frame velocity and acceleration using current rotation
        rot_W2B = get_rot_matrix(self.state["theta"])
        vel_b = np.dot(rot_W2B, self.state["xdot"]) # body-frame velocity
        acc_b = np.dot(rot_W2B, self.state["xdd"]) # body-frame acceleration #TODO: get world acceleration

        adapt_xin = np.atleast_2d(np.hstack((vel_b, acc_b))).T # TODO: move to own function
        assert(adapt_xin.shape == (6, 1))
        self.adapt_xin = adapt_xin
        

        # Forward Pass (compute output with W and V) to get adaptive body acceleration 
        acc_ad_b = self.ad_net.forward(adapt_xin)

        # convert body frame adaptive acceleration to world frame
        rot_B2W = np.linalg.pinv(rot_W2B)
        acc_w = np.ndarray.flatten(np.dot(rot_B2W, acc_ad_b))
        assert(acc_w.shape == (3,))
        


        self.v_ad = acc_w

    def update_model_track_err(self):
        "model_track_err = x_r - x"
        # TODO: in body frame?

        pos_err_w = self.x_r[:3] - self.state["x"]
        vel_err_w = self.x_r[3:] - self.state["xdot"]

        rot_W2B = get_rot_matrix(self.state["theta"])

        pos_err_b = np.dot(rot_W2B, pos_err_w)
        vel_err_b = np.dot(rot_W2B, vel_err_w)

        model_track_err_b = np.atleast_2d(np.hstack((pos_err_b, vel_err_b))).T
        assert(model_track_err_b.shape == (6,1))
        self.model_track_error = model_track_err_b
        self.m_track_hist.append(np.ndarray.flatten(model_track_err_b))

    def compute_v_tot(self):
        "v_tot = v_cr + v_lc - v_ad"
        # Set input to zero if not used
        if not self.use_adapt:
            self.v_ad = np.zeros((3,))
            print("Not using adaptive element")

        v_tot = self.v_cr + self.v_lc + self.v_ad #! why do we add v_ad? paper is subtract
        assert(v_tot.shape == (3, ))
        self.v_tot = v_tot

        # Save history
        self.v_ad_hist.append(self.v_ad)
        self.v_lc_hist.append(self.v_lc)
        self.v_cr_hist.append(self.v_cr)

    def train_adapt(self):
        """Train network."""
        self.update_model_track_err() # body frame
        assert(self.model_track_error.shape == (6, 1))
        self.ad_net.updateWeights(self.adapt_xin, self.Rp, self.Rd, self.model_track_error)
        
        

def main():
    # Initialize quadrotor state #TODO: make to general function, not sure where
    deviation = 100
    state = {"x": np.array([5, 0, 10]),
             "xdot": np.zeros(3,),
             "xdd": np.zeros(3,),
             "theta": np.radians(np.array([0, 0, 0])),  
             "thetadot": np.radians(np.array([0, 0, 0]))  
            # "thetadot" : np.radians(2 * deviation * np.random.rand(3,) - deviation) #add some noise
             }
             
    # Initialize MRAC controller
    use_adapt = True
    mrac = MRAC_control(state, use_adapt=use_adapt)


    # Initialize quadrotor dynamics and logger and parameters
    quad_dyn = QuadDynamics()
    quad_hist = QuadHistory()
    

    # Initialize visualization
    fig = plt.figure(0)
    ax = fig.add_subplot(2, 3, 1, projection='3d')
    ax_x_error = fig.add_subplot(2, 3, 2)
    ax_xd_error = fig.add_subplot(2, 3, 3)
    ax_xdd_error = fig.add_subplot(2, 3, 4)
    ax_th_error = fig.add_subplot(2, 3, 5)
    ax_thr_error = fig.add_subplot(2, 3, 6)

    # Initialize controller errors # TODO: move to objects
    integral_p_err = None
    integral_v_err = None


    # Step through simulation
    num_steps = 1000
    for t in range(num_steps):
        # quad_dyn.param_dict["m"] = 10# losing power
        # print("t", t)
        # Set desired position
        # des_pos = np.array([5 + 3*np.sin(0.1*t), 0.01*t, 10])
        des_pos = np.array([7, 0, 10])
        mrac.x_c = np.hstack((des_pos, np.array([0, 0, 0])))

        # MRAC Loop
        mrac.update_model_track_err() # updates model_track_err
        mrac.ref_model() # updates self.v_cr
        mrac.linear_compensator() # updates v_lc
        mrac.adaptive_element() # update self.v_ad

        mrac.compute_v_tot() # sums to v_tot
        des_theta, des_thrust_pc = mrac.dynamic_inversion(quad_dyn.param_dict)

        mrac.update_model_state(quad_dyn.param_dict["dt"]) # integrate model acc 
        mrac.plant(des_theta, quad_dyn, des_thrust_pc)

        # Train (update weight given model error)
        mrac.train_adapt()

        # update history for plotting
        ax.cla()
        des_vel = [0,0,0] #! temp
        # update history for plotting
        quad_hist.update_history(mrac.state, np.degrees(
            des_theta), des_vel, des_pos, quad_dyn.param_dict["dt"])

    print("plotting")
    print(np.array(mrac.m_track_hist).shape)

    # for t in range(100):
    t = num_steps - 1
    # # Visualize quadrotor and angle error
    ax.cla()
    visualize_quad_quadhist(ax, quad_hist, t)
    visualize_error_quadhist(
        ax_x_error, ax_xd_error, ax_th_error, ax_thr_error, ax_xdd_error, quad_hist, t, quad_dyn.param_dict["dt"], mrac.m_x_hist, mrac.m_xd_hist)
    # plt.show()

    # Save 
    if use_adapt:
        np.savetxt('yes_adapt.txt', np.array(mrac.m_track_hist)[:, :3])
    else:
        np.savetxt('no_adapt.txt', np.array(mrac.m_track_hist)[:, :3])

    # Plot tracking error
    plt.figure(1)
    plt.plot(np.array(mrac.m_track_hist)[:, :3])
    plt.legend(["x", "y", "z"])
    plt.ylim([-1,1])
    plt.title("Tracking Error (Adaptive)")
    

    # Plot accelerations
    plt.figure(2)
    plt.title("Component accelerations")
    plt.plot(np.array(mrac.v_ad_hist)[:,0]) # plot x
    plt.plot(np.array(mrac.v_cr_hist)[:, 0])
    plt.plot(np.array(mrac.v_lc_hist)[:, 0])
    plt.legend(["Adaptive", "Ref Model", "Linear Compensator"])

    plt.show()


# def test_net():
#     state = {"x": np.array([5, 0, 10]),
#              "xdot": np.zeros(3,),
#              "theta": np.radians(np.array([0, 0, -25])),
#              "thetadot": np.radians(np.array([0, 0, 0]))
#              }
#     net = MRAC_Adapt()
#     mrac = MRAC_control(state)

#     # x_in: body velocity (3, ), body acceleration (3, )
#     x_in = np.array([[1, 0, 0, 0, 0, 0]]).T  # ! Mock input
#     assert(x_in.shape == (6, 1))

#     ## NN iteration
#     # Forward Pass (compute output with W and V)
#     acc_ad_b = net.forward(x_in)
#     # print(acc_ad_b)

#     # Back prop (update W, V)
#     track_error = np.array([[0.1, 0, 0, 0, 0, 0]]).T  # ! mock error
#     assert(track_error.shape == (6, 1))
#     net.updateWeights(x_in, mrac.Rp, mrac.Rd, track_error)


if __name__ == '__main__':
    # test_net()
    main()

