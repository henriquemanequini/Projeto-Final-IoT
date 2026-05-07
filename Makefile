PYTHON      := python
UVICORN     := uvicorn
PIP         := pip
PYTEST      := pytest
AWS         := aws
REGION      := sa-east-1
STACK_DB    := estacionamento-dynamodb
STACK_IOT   := estacionamento-iot-core
STACK_RULE  := estacionamento-iot-rule
STACK_API   := estacionamento-api
STACK_COG   := estacionamento-cognito
BUILD_DIR   := .build

.PHONY: install test run-local lint \
        deploy-db deploy-iot deploy-rule deploy-api deploy-cognito \
        destroy-db destroy-iot destroy-rule destroy-api destroy-cognito destroy \
        package-lambda package-api logs-lambda

# ---------------------------------------------------------------------------
# Dev local
# ---------------------------------------------------------------------------

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) -v

run-local:
	MODO_LOCAL=true $(UVICORN) src.api.main:app --reload --port 8000

lint:
	ruff check src/ tests/ scripts/ || true

# ---------------------------------------------------------------------------
# Deploy infra — rode na ordem: db → iot → rule → api
# ---------------------------------------------------------------------------

deploy-db:
	$(AWS) cloudformation deploy \
		--template-file infra/dynamodb.yaml \
		--stack-name $(STACK_DB) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM

deploy-iot:
	$(AWS) cloudformation deploy \
		--template-file infra/iot.yaml \
		--stack-name $(STACK_IOT) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM

# Requer que a Lambda já exista (deploy-rule empacota internamente)
package-lambda:
	mkdir -p $(BUILD_DIR)/atualiza_estado
	cp src/lambdas/atualiza_estado/handler.py $(BUILD_DIR)/atualiza_estado/
	cd $(BUILD_DIR)/atualiza_estado && zip -r ../atualiza_estado.zip .
	$(AWS) s3 cp $(BUILD_DIR)/atualiza_estado.zip s3://$(LAMBDA_BUCKET)/atualiza_estado.zip

deploy-rule: package-lambda
	$(AWS) cloudformation deploy \
		--template-file infra/iot-rule.yaml \
		--stack-name $(STACK_RULE) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--parameter-overrides LambdaBucket=$(LAMBDA_BUCKET)

package-api:
	mkdir -p $(BUILD_DIR)/api
	$(PIP) install -r requirements.txt --target $(BUILD_DIR)/api --quiet
	cp -r src $(BUILD_DIR)/api/
	cd $(BUILD_DIR)/api && zip -r ../api.zip . -x "*.pyc" -x "__pycache__/*"

deploy-api: package-api
	$(AWS) cloudformation deploy \
		--template-file infra/api.yaml \
		--stack-name $(STACK_API) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--parameter-overrides \
			CorsOrigin=$(CORS_ORIGIN) \
			LambdaBucket=$(LAMBDA_BUCKET)

deploy-cognito:
	$(AWS) cloudformation deploy \
		--template-file infra/cognito.yaml \
		--stack-name $(STACK_COG) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM

# ---------------------------------------------------------------------------
# Destroy — ordem inversa
# ---------------------------------------------------------------------------

destroy-api:
	$(AWS) cloudformation delete-stack --stack-name $(STACK_API) --region $(REGION)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_API) --region $(REGION)

destroy-rule:
	$(AWS) cloudformation delete-stack --stack-name $(STACK_RULE) --region $(REGION)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_RULE) --region $(REGION)

destroy-iot:
	$(AWS) cloudformation delete-stack --stack-name $(STACK_IOT) --region $(REGION)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_IOT) --region $(REGION)

destroy-cognito:
	$(AWS) cloudformation delete-stack --stack-name $(STACK_COG) --region $(REGION)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_COG) --region $(REGION)

destroy-db:
	$(AWS) cloudformation delete-stack --stack-name $(STACK_DB) --region $(REGION)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_DB) --region $(REGION)

destroy: destroy-api destroy-rule destroy-iot destroy-cognito destroy-db
	@echo "Todos os stacks removidos."

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

logs-lambda:
	$(AWS) logs tail /aws/lambda/atualiza_estado --follow --region $(REGION)
