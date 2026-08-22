from pathlib import Path
import unittest


ROLE = Path(__file__).resolve().parents[1]


class RoleContractTest(unittest.TestCase):
    def test_recovery_service_is_bounded(self) -> None:
        service = (ROLE / "files" / "podhaus-nfs-container-recovery.service").read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("TimeoutStartSec=45", service)
        self.assertIn("After=docker.service", service)

    def test_timer_recurs_from_service_inactivity(self) -> None:
        timer = (ROLE / "files" / "podhaus-nfs-container-recovery.timer").read_text()
        self.assertIn("OnUnitInactiveSec=60s", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_role_removes_gate_and_owns_efi_pass_number(self) -> None:
        tasks = (ROLE / "tasks" / "main.yml").read_text()
        self.assertIn("wait-for-qnap-nfs.service", tasks)
        self.assertIn("10-wait-for-qnap.conf", tasks)
        self.assertIn("state: absent", tasks)
        self.assertIn("/boot/efi", tasks)
        self.assertIn("shortname=winnt 0 2", tasks)


if __name__ == "__main__":
    unittest.main()
