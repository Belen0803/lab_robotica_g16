import math

import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions

import tf2_ros
import tf2_geometry_msgs  # noqa: F401  (registers PoseStamped transform support on Buffer)

from geometry_msgs.msg import TwistStamped
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data

class TurtlebotController(Node):

    def __init__(self):
        super().__init__('robot_controller')

        # Tolerance for reaching the goal
        self.goal_tol = 0.15
        
        # Parámetros del controlador
        self.declare_parameter('max_linear_vel', 0.16)
        self.declare_parameter('max_angular_vel', 1.0)
        self.declare_parameter('k_linear', 0.8)
        self.declare_parameter('k_angular', 2.0)


        # Initialize internal data
        self.goal = PoseStamped()
        self.goal_received = False


        # Datos del sensor laser
        self.front_distance = None
        self.left_clearance = 0.0
        self.right_clearance = 0.0
        self.last_scan_time = None

        # Estado de la evasion
        self.avoiding = False
        self.avoid_direction = 1.0

        # Parametros de seguridad
        self.declare_parameter('obstacle_distance', 0.55)
        self.declare_parameter('clear_distance', 0.75)
        self.declare_parameter('avoid_turn_vel', 0.7)




        # TF2 buffer/listener
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # Subscribers / publishers
        self.cmd_vel_pub = self.create_publisher(TwistStamped, 'cmd_vel', 10)
        self.create_subscription(PoseStamped, 'goal_pose', self.goal_callback, 10)

        self.get_logger().info('Robot controller started')

        # Commanding the robot at a fixed rate (10Hz),
        self.timer = self.create_timer(0.1, self.command)


    def stop_robot(self):
        # Stop turtlebot
        self.get_logger().info('Stop robot')
        self.publish(0.0, 0.0)

    def goal_callback(self, goal):
        self.get_logger().info(
            f'Goal received! x: {goal.pose.position.x:.2f}, y: {goal.pose.position.y:.2f}')
        self.goal = goal
        self.goal_received = True

    def command(self):
        
        # Check if we already received data
        if not self.goal_received:
            self.get_logger().info('Goal not received. Waiting...')
            return

        # Check if the final goal has been reached
        if self.goal_reached():
            self.get_logger().info('GOAL REACHED!!! Stopping!')
            self.publish(0.0, 0.0)
            self.goal_received = False
            return


        # 3. Transformar el objetivo al sistema del robot
        self.goal.header.stamp = rclpy.time.Time().to_msg()

        try:
            local_goal = self.tf_buffer.transform( #transforma las coordenadas del objetivo al sistema local del robot.
                self.goal, 'base_footprint'
            )
        except (tf2_ros.LookupException,
                tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as ex:
            self.get_logger().warn(f'Problem TF: {ex}')
            self.publish(0.0, 0.0)
            return

        # Obtenemos las coordenadas relativas a nuestro robot.
        x = local_goal.pose.position.x
        y = local_goal.pose.position.y

        # Calcular distancia y error de orientación
        distance = math.hypot(x, y) #Usamos el teorema de pitágoras para calcular la distancia y así obtener el error para el proporcional
        angle = math.atan2(y, x) # Error de la orientación

        # Leer parámetros que se han definido previamente
        max_v = self.get_parameter('max_linear_vel').value
        max_w = self.get_parameter('max_angular_vel').value
        k_v = self.get_parameter('k_linear').value
        k_w = self.get_parameter('k_angular').value

        # Calcular velocidad angular y limitarla, como hemos hecho un proporcional pues tendremos que la acción de control es proporcional al error.
        angular = k_w * angle
        angular = max(-max_w, min(max_w, angular))

        #Calcular velocidad lineal para mandarla
        # Primero orientamos el robot hacia el objetivo cuando el error en la velocidad angular es muy grande
        if abs(angle) > 0.25:
            linear = 0.0
        else:
            linear = min(max_v, k_v * distance)

        # 9. Enviar las velocidades al robot
        self.publish(linear, angular)

        
        # Publish velocity command
        self.publish(linear, angular)

    def goal_reached(self):
        # Return True if the goal was reached, False otherwise

        if self.goal_received:
            # Update the goal timestamp to avoid issues with the TF transform
            self.goal.header.stamp = rclpy.time.Time().to_msg()

            try:
                pose_transformed = self.tf_buffer.transform(self.goal, 'base_footprint')
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as ex:
                self.get_logger().info(f'Problem TF: {ex}')
                return False

            goal_distance = math.sqrt(pose_transformed.pose.position.x ** 2 + pose_transformed.pose.position.y ** 2)
            if goal_distance < self.goal_tol:
                return True

        return False

    def publish(self, lin_vel, ang_vel):

        # Twist is a datatype for velocity
        move_cmd = TwistStamped()
        move_cmd.header.stamp = rclpy.time.Time().to_msg()
        move_cmd.twist.linear.x = lin_vel
        move_cmd.twist.angular.z = ang_vel

        self.get_logger().info(f'Commanding lv: {lin_vel:.2f}, av: {ang_vel:.2f}')
        self.cmd_vel_pub.publish(move_cmd)


def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)

    robot = TurtlebotController()

    # Tell user how to stop TurtleBot
    robot.get_logger().info('To stop robot CTRL + C')

    try:
        rclpy.spin(robot)
    except KeyboardInterrupt:
        pass

    # What to do when you CTRL + C
    robot.stop_robot()

    robot.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
