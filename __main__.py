import pulumi
import pulumi_gcp as gcp
#from pulumi_kubernetes.core.v1 import TolerationArgs,ResourceRequirementsArgs,Namespace,ObjectMetaArgs, ContainerArgs, PodSpecArgs, PodTemplateSpecArgs, Service, ServicePortArgs, ServiceSpecArgs
import pulumi_kubernetes as k8s
#import pulumi_kubernetes.core.v1 as core

# Cluster configuration variables
project_id = "your-gcp-project-id"  # Google Cloud project ID
location = "us-centra11"  # Google Cloud zone
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
    location=location,
    project=project_id,
    deletion_protection=False
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
        guest_accelerators=[gcp.container.NodePoolNodeConfigGuestAcceleratorArgs(
            type=gpu_type,
            count=gpu_count_per_node
        )],
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


llm_namespace = k8s.core.v1.Namespace("vllm")
deploy_name="llm-gke-inference"
# Create a deployment that requests GPU resources
gpu_deployment = k8s.apps.v1.Deployment(deploy_name,
     metadata=k8s.meta.v1.ObjectMetaArgs(
        labels={
            "app": deploy_name,
        },
        name=deploy_name,
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels={
                "app": deploy_name,
            },
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels={
                    "app": deploy_name,
                },
            ),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="llm-container",
                        image="nvidia/cuda:10.0-base",  # Using the CUDA image as an example
                        resources=k8s.core.v1.ResourceRequirementsArgs(
                            requests={
                                "nvidia.com/gpu": 1,  # Requesting one GPU
                            },
                        ),
                    ),
                ],
                node_selector={
                    "cloud.google.com/gke-accelerator": gpu_type,  # Ensuring the pod is scheduled on GPU-enabled nodes
                },
                tolerations=[  # Toleartions ensure the pod can be scheduled on nodes with taints that match these.
                    k8s.core.v1.TolerationArgs(
                        key="nvidia.com/gpu",
                        operator="Exists",
                        effect="NoSchedule",
                    ),
                ],
            ),
        ),
    ),
)

# Export the cluster name and Kubeconfig file for accessing the cluster
pulumi.export('cluster_name', cluster.name)
pulumi.export("llm_namespace", llm_namespace.metadata["name"])
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