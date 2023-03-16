job "example" {
    region      = "global"
    datacenters = ["homelab"]
    type        = "service"

  group "alloc" {
    count = 3
    task "alpine" {
      driver = "docker"

      config {
        image = "alpine:latest"
        command = "sh"
        args = ["-c", "while true; do sleep 300; done"]
      }
      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
