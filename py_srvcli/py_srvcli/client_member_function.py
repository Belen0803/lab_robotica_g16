
import sys

import rclpy
from rclpy.node import Node

from tutorial_interfaces.srv import AddThreeInts


class MinimalClientAsync(Node):

    def __init__(self):
        super().__init__('minimal_client_async')

        self.cli = self.create_client(
            AddThreeInts,
            'add_three_ints'
        )

        while not self.cli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info(
                'service not available, waiting again...'
            )

    def send_request(self, a, b, c):
        request = AddThreeInts.Request()
        request.a = a
        request.b = b
        request.c = c

        return self.cli.call_async(request)


def main():
    if len(sys.argv) != 4:
        print('Uso: client NUM1 NUM2 NUM3')
        return

    a = int(sys.argv[1])
    b = int(sys.argv[2])
    c = int(sys.argv[3])

    rclpy.init()

    node = MinimalClientAsync()
    future = node.send_request(a, b, c)

    rclpy.spin_until_future_complete(node, future)

    response = future.result()

    node.get_logger().info(
        'Result of add_three_ints: for %d + %d + %d = %d' %
        (a, b, c, response.sum)
    )

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
