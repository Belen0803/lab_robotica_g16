# Copyright 2016 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language g
import rclpy
from rclpy.node import Node

from tutorial_interfaces.msg import Num


class MinimalPublisher(Node):

    def __init__(self):
        super().__init__('minimal_publisher')

        self.publisher_ = self.create_publisher(
            Num, 'topic', 10
        )

        self.timer = self.create_timer(
            0.5, self.timer_callback
        )

        self.i = 0

    def timer_callback(self):
        msg = Num()
        msg.num = self.i

        self.publisher_.publish(msg)

        self.get_logger().info(
            'Publishing: "%d"' % msg.num
        )

        self.i += 1


def main():
    rclpy.init()

    node = MinimalPublisher()
    rclpy.spin(node)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
