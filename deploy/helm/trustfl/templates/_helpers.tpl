{{/*
Expand the name of the chart.
*/}}
{{- define "trustfl.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "trustfl.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "trustfl.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "trustfl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for a component
*/}}
{{- define "trustfl.selectorLabels" -}}
app.kubernetes.io/name: {{ include "trustfl.name" . }}-{{ .component }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Image digest resolution and immutability validation.
Fails rendering if an immutable sha256 digest is not supplied or if mutable 'latest' is given.
*/}}
{{- define "trustfl.image" -}}
{{- $digest := default .root.Values.global.imageDigest .componentValues.image.digest -}}
{{- if not $digest -}}
{{- fail (printf "Production deployment requires an immutable image digest for %s (e.g. sha256:abcdef...). Mutable image tags are forbidden." .component) -}}
{{- end -}}
{{- if or (hasPrefix "latest" $digest) (contains "latest" $digest) -}}
{{- fail (printf "Mutable image tag 'latest' is forbidden for %s. An immutable sha256 digest is required." .component) -}}
{{- end -}}
{{- if not (hasPrefix "sha256:" $digest) -}}
{{- fail (printf "Image digest for %s must begin with 'sha256:'. Got: %s" .component $digest) -}}
{{- end -}}
{{- printf "%s/%s@%s" .root.Values.global.imageRegistry .componentValues.image.name $digest -}}
{{- end }}
