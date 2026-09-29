# Physical SO-101 Hardware

Install the serial dependency with `pip install 'jolly-cli[hardware]'`.

Jolly's `SO101HardwareDriver` sends Feetech STS3215 packets directly at the
SO-101 default 1,000,000 baud. The configured motor IDs default to the common
SO-101 sequence of 1 through 6. Each physical arm requires measured calibration.

Generate a template, then replace all placeholder zero points, directions, and
gripper endpoints before movement.

```bash
jolly hardware calibration-example --output calibration.json
jolly hardware scan --port /dev/ttyACM0 --calibration calibration.json --json
jolly hardware state --port /dev/ttyACM0 --calibration calibration.json --json
jolly hardware move --port /dev/ttyACM0 --calibration calibration.json \
  --joints '0,0,0,0,0' --gripper 0 --confirm-hardware --json
jolly hardware benchmark --port /dev/ttyACM0 --calibration calibration.json \
  --seed 42017 --cases 3 --confirm-hardware --json
jolly hardware stop --port /dev/ttyACM0 --calibration calibration.json
```

The physical benchmark makes bounded movements of at most five degrees from the
measured starting pose. It scores measured motor-position error and returns to
the starting pose. Torque stays enabled to hold that pose. Support the arm
before `jolly hardware stop`. Communication failures trigger a best-effort
torque disable. Clear the workspace and keep an emergency power cutoff nearby.

Physical hardware scores and PyBullet contact-task scores are separate. Jolly
never labels a physics result as a physical-hardware result.

Protocol and hardware references:

- https://huggingface.co/docs/lerobot/en/so101
- https://pages.switch-science.com/comparison/files/feetech/serial-sts/STS3215_datasheet.pdf
