import pulumi
import pulumi_gcp as gcp

# Cluster configuration variables
project_id = "your-gcp-project-id"  # Google Cloud project ID
zone = "us-central-1c"  # Google Cloud zone
cluster_name = "llm-gpu-cluster"
kubernetes_version = "1.28"  # specify the desired Kubernetes version
node_pool_name = "gpu-node-pool"
machine_type="g2-standard-8"
gpu_type = "nvidia-l4"  # specify the GPU type for the cluster
gpu_count_per_node = 1  # GPUs per node
UseSpot=True 

# Create a GKE cluster
cluster = gcp.container.Cluster(cluster_name,
    initial_node_count=1,  # one node in default node pool (can be changed or default pool can be removed if needed)
    min_master_version=kubernetes_version,
    location=zone,
    project=project_id
)

# Create a GKE node pool with GPUs
gpu_node_pool = gcp.container.NodePool(node_pool_name,
    cluster=cluster.name,
    location=cluster.location,
    node_count=1,  # specify the number of nodes in the GPU node pool
    node_config=gcp.container.NodePoolNodeConfigArgs(
        preemptible=UseSpot,
        machine_type=machine_type,  # specify the machine type
        oauth_scopes=[
            "https://www.googleapis.com/auth/compute",
            "https://www.googleapis.com/auth/devstorage.read_only",
            "https://www.googleapis.com/auth/logging.write",
            "https://www.googleapis.com/auth/monitoring",
        ],
        guest_accelerator=gcp.container.NodePoolNodeConfigGuestAcceleratorArgs(
            type=gpu_type,
            count=gpu_count_per_node
        ),
        metadata={"disable-legacy-endpoints": "true"},
        labels={"llm-node": "true"},
        taints=[
            gcp.container.NodePoolNodeConfigTaintArgs(
                key="llmworkload",
                value="true",
                effect="NO_SCHEDULE",
            )
        ]
    ),
    autoscaling=gcp.container.NodePoolAutoscalingArgs(
        min_node_count=0,
        max_node_count=3  # setting max number of nodes for auto-scaling
    ),
    management=gcp.container.NodePoolManagementArgs(
        auto_repair=True,
        auto_upgrade=True
    ),
    project=project_id,
)

# Export the cluster name and Kubeconfig file for accessing the cluster
pulumi.export('cluster_name', cluster.name)
kubeconfig = pulumi.Output.all(cluster.name, cluster.endpoint, cluster.master_auth).apply(lambda args: '''
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: {1}
    server: https://{0}
  name: {2}
contexts:
- context:
    cluster: {2}
    user: {2}
  name: {2}
current-context: {2}
kind: Config
preferences: {{}}
users:
- name: {2}
  user:
    auth-provider:
      config:
        cmd-args: config config-helper --format=json
        cmd-path: gcloud
        expiry-key: '{{.credential.token_expiry}}'
        token-key: '{{.credential.access_token}}'
      name: gcp
'''.format(args[1], args[2]['cluster_ca_certificate'], args[0]))

pulumi.export('kubeconfig', kubeconfig)