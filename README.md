# Documentation

### Background
Instances of Pipelines that have been invoked are called ```PipelineRuns```.  These PipelineRun objects contain the configuration of the pipeline's instance, the logs of each ```Task```, ```ClusterTask```, ```Step```, the injected configuration from the webhook, and the ```Workspace``` used by each to store the build data.  When utilizing multi-Tasks, or ClusterTasks, it is a requirement to provide persistent storage to hold the build's data.  This is done by attaching a ```PersistentVolumeclaim``` to the PipelineRun.  While having a large amount of PipelineRun objects in the cluster is benign to kubernetes, it has the potential to rapidly fill up the associated storage because of these attached workspaces.  Because of this, it behooves the operations team to curate, or clean-up, old PipelineRun objects, thus freeing up the associated workspace storage.

### Benefits
#### Scalability.
An operator approach to cleaning up PipelineRuns is better than using Scheduled ```Jobs``` because:
```
1.  By using native kubernetes eventing, it's faster...
2.  PipelineRuns are managed in real time vs waiting (and hoping) that a Job does what it needs to do.
3.  One Cluster-Scoped PipelineRunCurator operator can be used to clean-up ALL PipelineRuns on the Cluster
4.  Additional logic can be added to the event handlers to do more interesting things.
```
#### RBAC
This operator takes advantage of native kubernetes Role-Based Access Controls with ```ClusterRoles``` and ```ClusterRoleBindings``` to the ```ServiceAccount```.  These roles are tightly scoped to not give the operator access that it does not need. Privileged access is not required.  This operator could very easily be changed to a Namespaced-scoped Operator with even more reduced permissions.  If so, this operator would need to be deployed in the specific namespace where the Pipelines are to be ran and the ClusterRoles converted to Roles
#### Kopf
Because this operator was created using the Python Operator Framework ```Kopf```, the technical barrier to entry was much lower.  Nobody had to dust off Golang books to make this operator.   <br/>
<br/>Kopf supports "Operator Peering", which means that a locally running operator on the developer's workstation can "Interrupt" the running operator on the cluster and cede control of handlers to the version running on the workstation.  This allows for tighter development cycles. As such, this operator was developed very quickly.

### Caveats
#### Many git repos to one Pipeline
When using Tekton at scale, it is important to understand the many-to-one relationship between git repositories and pipelines.  That is, multiple repos can leverage the same pipeline infrastructure.  Because of this, it is important to differentiate between PipelineRun objects based on the repos name that invoked it.  This is done by standardizing the parameter name that is used to pass the repository's name in all Tekton objects (```EventListener```, ```TriggerTemplate```, ```TriggerBinding```, and ```Pipeline```).  This parameter can then be used to name and manage the PipelineRun objects.  This parameter name needs to be passed to the PipelineRunCurator object described below in the Custom Resources section.  The ```generateName``` metadata option in the TriggerTemplate should also use this "repo name" parameter to name the PipelineRun objects according to the repo that invoked it. The same thing should be done to name the Workspace in the same TriggerTemplate.

#### Namespaces and Projects (Openshift)
Because Openshift pre-dates kubernetes and was later re-platformed, there are two different objects that describe ```Namespaces```.  An Openshift ```Project``` is synonymous with kubernetes namespaces.  In the included 'plr-curator-kopf.yaml' deployment yaml, a Project is used (with corresponding ```SecurityContextConstraints``` config.  If deploying this operator to "vanilla" kubernetes (ie not Openshift), then a standard Namespace object should be used instead of Project.
#### 'oc' client vs 'kubectl'
Because we are using Openshift OKD here, the client that is used to interact with the cluster is the provided 'oc' binary.  This binary basically wraps 'kubectl' and extends it for Openshift-specific things, like SCCs, Projects, and Routes.

#### Secrets
A ```Secret``` object is also included in the 'plr-curator-kopf.yaml' file that is used for pulling the operator's image from a container registry.  In this Secret object, we are using the '$HARBOR_CFG' variable to insert the secret.  When running the 'setup_plr-curator.sh' script to deploy the operator, make sure to have this secret exported in your shell as HARBOR_CFG.  It should contain the Base64-encoded pull secret for your registry.
###### TODO:  convert this to a Kustomize ```secretGenerator```

### Custom Resources
The ```PipelineRunCurator``` resource is a kubernetes Custom Resource (CRD) that allows for the configuration of the PipelinRunCurator Operator.  PLRC objects should be created in the namespace that the operator is deployed in (all other namespaces will be ignored).
The configuration elements that are needed for this object are as follows:
```
1.  'plrlimit' - this should be set to the number of PipelineRun objects to retain.
2.  'namespace' - this should be set to the namespace that you want the PLR Curator to watch
3.  'repoparam' - this should be set to the git repo parameter that you want to use as the "repo name" in the pipelines.  Ex: git-repo-name 
```

### Event Handling
All EventHandlers are located in the 'handlers.py' file.
<br/> <br/>
When the Operator sees a new PipelineRunCurator resource deployed inside the curator's namespace, the operator's ```on-create``` event handler is run and processes the new PLRC configuration.  <br/> <br/>First, the operator checks to see if all of the proper configuration elements are present (PLRLIMIT, Namespace, RepoParam).   <br/> <br/>Second, it checks to see if there is an existing PLRC for the configured ```Namespace```.  If it detects an existing configuration for this namespace, it delete's the new PLRC resource because this is a duplicate configuration and logs accordingly.  There should only be one PLRC object per-namespace that you want to monitor.  <br/><br/>When the operator first starts up, it processes each PLRC object (ALL) with an ```on-resume``` event handler and does basic sanity checking for each configuration and also checks for duplicates in all namespaces.
 <br/>
The same event handler is used for PipelineRun objects on both ```on-resume``` and ```on-create``` events.  This means that ALL PipelineRuns will be curated on start-up of the operator and on creation of new PipelineRuns.

### Deploying the Operator
##### 1.  export the registry pull secret (base64 encoded) as HARBOR_CFG
```
export HARBOR_CFG=`cat harbor-secret.json |base64`
```
##### 2.  Run the setup_plr-curator.sh script
```
./setup_plr-curator.sh
```


