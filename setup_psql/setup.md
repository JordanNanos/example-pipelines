# Setup Postgres on a Kubernetes Cluster

Apply the .yaml files above in order:
```
kubectl apply -f *.yaml
```
Check which IP was allocated to postgres:
```
kubectl get svc
```
Check that the postgres db is responding:
```
curl a.b.c.d:5432
```
Response will show `curl: (52) Empty reply from server` 

