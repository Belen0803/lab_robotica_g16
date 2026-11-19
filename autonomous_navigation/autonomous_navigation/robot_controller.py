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
        # Guardamos las lecturas del láser para comprobar
        # si hay un camino libre hacia el objetivo.
        self.scan_msg = None

        # Distancia al objetivo cuando encontramos un obstáculo.
        self.avoid_start_distance = None




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

        self.create_subscription(
            LaserScan,
            'scan',
            self.scan_callback,
            qos_profile_sensor_data
        )


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


    def scan_callback(self, msg):
        self.scan_msg = msg
        # Separamos las medidas del laser en tres sectores
        front = []
        left = []
        right = []

        for i, distance in enumerate(msg.ranges):

            # Ignoramos lecturas invalidas
            if math.isnan(distance) or distance <= 0:
                continue

            if math.isinf(distance):
                distance = msg.range_max
            elif distance < msg.range_min:
                continue

            distance = min(distance, msg.range_max)

            # Calculamos el angulo correspondiente a cada medida
            angle = msg.angle_min + i * msg.angle_increment
            angle = math.atan2(math.sin(angle), math.cos(angle))
            degrees = math.degrees(angle)

            # Clasificamos las medidas segun su direccion
            if abs(degrees) <= 35:
                front.append(distance)

            elif 35 < degrees <= 110:
                left.append(distance)

            elif -110 <= degrees < -35:
                right.append(distance)

        # Obtenemos la distancia minima de cada sector
        self.front_distance = min(front) if front else None
        self.left_clearance = min(left) if left else 0.0
        self.right_clearance = min(right) if right else 0.0

        # Guardamos cuando hemos recibido la lectura
        self.last_scan_time = self.get_clock().now()


    def goal_direction_clear(self, angle, distance):

        # Comprobamos si tenemos lecturas del láser.
        if self.scan_msg is None:
            return False

        msg = self.scan_msg
        measurements = []

        # Distancia que necesitamos tener libre
        required = min(distance + 0.20, msg.range_max - 0.05)

        for i, reading in enumerate(msg.ranges):

            # Calculamos el ángulo de cada lectura
            ray_angle = msg.angle_min + i * msg.angle_increment

            # Diferencia entre la dirección del láser y la meta
            error = math.atan2(
                math.sin(ray_angle - angle),
                math.cos(ray_angle - angle)
            )

            # Solo estudiamos las medidas cercanas
            # a la dirección del objetivo (+/- 12 grados)
            if abs(error) > math.radians(12):
                continue

            if math.isnan(reading) or reading < msg.range_min:
                continue

            if math.isinf(reading):
                if reading < 0:
                    continue
                reading = msg.range_max

            reading = min(reading, msg.range_max)
            measurements.append(reading)

        # Si no tenemos medidas suficientes, no damos
        # por despejada la trayectoria.
        if len(measurements) < 3:
            return False

        return min(measurements) > required



    
   
    def command(self):

        # Check if we already received data
        if not self.goal_received:
            return

        # Check if the final goal has been reached
        if self.goal_reached():
            self.get_logger().info('GOAL REACHED!!! Stopping!')
            self.publish(0.0, 0.0)
            self.goal_received = False
            self.avoiding = False
            return

        # Comprobamos que tenemos datos recientes del láser.
        if self.last_scan_time is None:
            self.publish(0.0, 0.0)
            return

        scan_age = (
            self.get_clock().now() - self.last_scan_time
        ).nanoseconds / 1e9

        if scan_age > 1.0 or self.front_distance is None:
            self.publish(0.0, 0.0)
            return

        # Transformar el objetivo al sistema del robot
        self.goal.header.stamp = rclpy.time.Time().to_msg()

        try:
            local_goal = self.tf_buffer.transform(
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

        obstacle_d = self.get_parameter('obstacle_distance').value

        # Si encontramos un obstáculo entramos en modo evasión.
        if not self.avoiding and self.front_distance < obstacle_d:

            self.avoiding = True
            self.avoid_start_distance = distance

            # Elegimos un lado y lo mantenemos
            # durante toda la evasión.
            if self.left_clearance >= self.right_clearance:
                self.avoid_direction = 1.0
            else:
                self.avoid_direction = -1.0

            self.get_logger().info('Starting wall following')

        # Seguimiento del contorno del obstáculo.
        if self.avoiding:

            # Volvemos al objetivo si la dirección está libre
            # y hemos progresado respecto al punto de encuentro.
            progress = (
                distance < self.avoid_start_distance - 0.20
            )

            clear_goal = self.goal_direction_clear(
                angle, distance
            )

            if progress and clear_goal:
                self.avoiding = False
                self.get_logger().info('Returning to goal')

            else:
                # Si el obstáculo está muy cerca por delante,
                # giramos sin avanzar.
                if self.front_distance < 0.40:

                    angular = self.avoid_direction * min(0.65, max_w)
                    self.publish(0.0, angular)
                    return

                # Seguimos el obstáculo por el lado elegido.
                # Si giramos a la izquierda, la pared queda
                # a nuestra derecha, y viceversa.
                if self.avoid_direction > 0:
                    side_distance = self.right_clearance
                else:
                    side_distance = self.left_clearance

                # Si faltan medidas laterales válidas,
                # giramos sin avanzar por seguridad.
                if side_distance <= 0.0:
                    self.publish(0.0, self.avoid_direction * 0.4)
                    return

                # Intentamos mantener 0.50 metros
                # respecto al obstáculo lateral.
                desired_distance = 0.50
                side_error = desired_distance - side_distance

                # Control proporcional de seguimiento de pared
                angular = (
                    self.avoid_direction * 1.3 * side_error
                )

                angular = max(-0.5, min(0.5, angular))

                # Avanzamos lentamente mientras bordeamos.
                linear = min(0.08, max_v)

                self.publish(linear, angular)
                return

        # Calcular velocidad angular y limitarla, como hemos hecho un proporcional pues tendremos que la acción de control es proporcional al error.
        angular = k_w * angle
        angular = max(-max_w, min(max_w, angular))

        #Calcular velocidad lineal para mandarla
        # Primero orientamos el robot hacia el objetivo cuando el error en la velocidad angular es muy grande
        if abs(angle) > 0.25:
            linear = 0.0
        else:
            linear = min(max_v, k_v * distance)

        # Enviar las velocidades al robot
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
